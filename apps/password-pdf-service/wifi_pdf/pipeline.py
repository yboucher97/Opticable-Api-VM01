from __future__ import annotations

import shutil
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import AppSettings, load_settings
from .exceptions import WorkDriveError
from .logging_utils import configure_logging
from .merge import merge_pdfs
from .models import WifiBatchRequest, parse_payload
from .qr import build_wifi_qr_string, generate_qr_png
from .renderer import PdfRenderer
from .utils import (
    batch_timestamp,
    ensure_directory,
    relative_to_root,
    sanitize_filename,
    write_json_file,
)
from .workdrive import ZohoWorkDriveClient
from .zoho_crm import ZohoCrmClient


@dataclass(slots=True)
class RecordOutput:
    index: int
    ssid: str
    pdf_path: str
    qr_path: str


@dataclass(slots=True)
class BatchOutput:
    batch_id: str
    building_name: str
    city: str | None
    template_name: str
    batch_dir: str
    merged_pdf_path: str
    txt_export_path: str
    zip_export_path: str
    ya_export_path: str
    manifest_path: str
    deleted_local_batch: bool
    record_count: int
    records: list[RecordOutput]
    crm_update: dict[str, Any] | None
    uploads: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["records"] = [asdict(record) for record in self.records]
        return payload


class WifiPdfPipeline:
    def __init__(self, settings: AppSettings, logger) -> None:
        self.settings = settings
        self.logger = logger
        self.renderer = PdfRenderer(settings, logger)

    def process_payload(self, raw_payload: Any) -> BatchOutput:
        batch = parse_payload(raw_payload)
        return self.process_batch(batch)

    def process_batch(self, batch: WifiBatchRequest) -> BatchOutput:
        batch_id = f"{batch_timestamp()}-{sanitize_filename(batch.building_name)}-{sanitize_filename(batch.template_name)}"
        root_dir = ensure_directory(self.settings.output.root_dir)
        batch_dir = ensure_directory(root_dir / batch_id)
        qr_dir = ensure_directory(batch_dir / "qr")
        individual_dir = ensure_directory(batch_dir / "individual")
        merged_dir = ensure_directory(batch_dir / "merged")

        self.logger.info(
            "Starting batch %s for building '%s' with %s records",
            batch_id,
            batch.building_name,
            len(batch.records),
        )

        record_outputs: list[RecordOutput] = []
        pdf_paths: list[Path] = []
        used_filename_bases: dict[str, int] = {}

        for index, record in enumerate(batch.records, start=1):
            filename_seed = sanitize_filename(f"{batch.building_name}-{record.unit_label or record.ssid}")
            filename_count = used_filename_bases.get(filename_seed, 0)
            used_filename_bases[filename_seed] = filename_count + 1
            filename_base = filename_seed if filename_count == 0 else f"{filename_seed}-{filename_count + 1}"
            qr_payload = build_wifi_qr_string(record)
            qr_path = qr_dir / f"{filename_base}-qr.png"
            pdf_path = individual_dir / f"{filename_base}.pdf"

            generate_qr_png(qr_payload, qr_path)
            self.renderer.render(
                record=record,
                building_name=batch.building_name,
                qr_path=qr_path,
                output_path=pdf_path,
                template_name=batch.template_name,
                sheet_number=index,
                sheet_total=len(batch.records),
            )

            pdf_paths.append(pdf_path)
            record_outputs.append(
                RecordOutput(
                    index=index,
                    ssid=record.ssid,
                    pdf_path=relative_to_root(pdf_path),
                    qr_path=relative_to_root(qr_path),
                )
            )
            self.logger.info("Generated PDF for SSID '%s'", record.ssid)

        txt_export_path = self._write_txt_export(batch_dir, batch)
        ya_export_path = self._write_ya_export(batch_dir, batch)

        merged_pdf_path = merge_pdfs(
            pdf_paths,
            merged_dir / f"{sanitize_filename(batch.building_name)}-merged.pdf",
        )
        zip_export_path = self._write_zip_export(batch_dir, batch, pdf_paths, merged_pdf_path)

        manifest_payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "batch_id": batch_id,
            "building_name": batch.building_name,
            "city": batch.city,
            "template_name": batch.template_name,
            "record_count": len(batch.records),
            "records": [asdict(record) for record in record_outputs],
            "merged_pdf_path": relative_to_root(merged_pdf_path),
            "txt_export_path": relative_to_root(txt_export_path),
            "zip_export_path": relative_to_root(zip_export_path),
            "ya_export_path": relative_to_root(ya_export_path),
            "workdrive_folder_id_requested": batch.workdrive_folder_id,
        }
        manifest_path = write_json_file(batch_dir / self.settings.output.manifest_filename, manifest_payload)

        uploads: list[dict[str, Any]] = []
        crm_update: dict[str, Any] | None = None
        deleted_local_batch = False

        if self.settings.workdrive.enabled:
            client = ZohoWorkDriveClient(self.settings.workdrive, self.logger)
            folder_id = client.resolve_upload_folder_id(batch.workdrive_folder_id)
            upload_candidates: list[Path] = []
            if self.settings.workdrive.upload_individual_pdfs:
                upload_candidates.extend(pdf_paths)
            if self.settings.workdrive.upload_merged_pdf:
                upload_candidates.append(merged_pdf_path)
            if self.settings.workdrive.upload_txt_export:
                upload_candidates.append(txt_export_path)
            if self.settings.workdrive.upload_zip_export:
                upload_candidates.append(zip_export_path)
            if self.settings.workdrive.upload_ya_export:
                upload_candidates.append(ya_export_path)

            for path in upload_candidates:
                uploads.append(client.upload_file(path, folder_id))

            if self.settings.workdrive.cleanup_local_after_upload:
                try:
                    shutil.rmtree(batch_dir)
                    deleted_local_batch = True
                except OSError as exc:
                    raise WorkDriveError(f"Upload succeeded but local cleanup failed: {exc}") from exc

        if batch.passwords_generated and batch.crm_record_id and self.settings.crm.enabled:
            crm_client = ZohoCrmClient(self.settings.crm, self.settings.workdrive, self.logger)
            crm_update = crm_client.update_generated_password_fields(
                record_id=batch.crm_record_id,
                passwords=[record.password or "" for record in batch.records],
                ssids=[record.ssid for record in batch.records],
            )

        if not self.settings.output.keep_qr_images and not deleted_local_batch:
            shutil.rmtree(qr_dir, ignore_errors=True)
            for record in record_outputs:
                record.qr_path = ""

        self.logger.info("Completed batch %s", batch_id)
        return BatchOutput(
            batch_id=batch_id,
            building_name=batch.building_name,
            city=batch.city,
            template_name=batch.template_name,
            batch_dir=relative_to_root(batch_dir),
            merged_pdf_path=relative_to_root(merged_pdf_path),
            txt_export_path=relative_to_root(txt_export_path),
            zip_export_path=relative_to_root(zip_export_path),
            ya_export_path=relative_to_root(ya_export_path),
            manifest_path=relative_to_root(manifest_path),
            deleted_local_batch=deleted_local_batch,
            record_count=len(batch.records),
            records=record_outputs,
            crm_update=crm_update,
            uploads=uploads,
        )

    def _write_txt_export(self, batch_dir: Path, batch: WifiBatchRequest) -> Path:
        safe_building_name = self._safe_building_label(batch.building_name)
        txt_path = batch_dir / f"Mot de passe {safe_building_name}.txt"
        lines = ["Logement\tMot de passe"]
        for record in batch.records:
            password = record.password or ""
            lines.append(f"{record.ssid}\t{password}")
        txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.logger.info("Generated TXT export for building '%s'", batch.building_name)
        return txt_path

    def _write_ya_export(self, batch_dir: Path, batch: WifiBatchRequest) -> Path:
        safe_building_name = self._safe_building_label(batch.building_name)
        ya_path = batch_dir / f"MDP_Site_APP {safe_building_name}.ya"
        first_line = batch.building_name if not batch.city else f"{batch.building_name} - {batch.city}"
        ssids = ",".join(record.ssid for record in batch.records)
        passwords = ",".join((record.password or "") for record in batch.records)
        vlans = ",".join(str(index * 10) for index in range(1, len(batch.records) + 1))
        ya_path.write_text(f"{first_line}\n{ssids}\n{passwords}\n{vlans}\n", encoding="utf-8")
        self.logger.info("Generated YA export for building '%s'", batch.building_name)
        return ya_path

    def _write_zip_export(
        self,
        batch_dir: Path,
        batch: WifiBatchRequest,
        pdf_paths: list[Path],
        merged_pdf_path: Path,
    ) -> Path:
        safe_building_name = self._safe_building_label(batch.building_name)
        zip_path = batch_dir / f"Mot de passe {safe_building_name}.zip"
        with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for pdf_path in pdf_paths:
                archive.write(pdf_path, arcname=pdf_path.name)
            archive.write(merged_pdf_path, arcname=merged_pdf_path.name)
        self.logger.info("Generated ZIP export for building '%s'", batch.building_name)
        return zip_path

    def _safe_building_label(self, building_name: str) -> str:
        safe_building_name = building_name.replace("/", "-").replace("\\", "-").strip()
        if not safe_building_name:
            safe_building_name = sanitize_filename(building_name)
        return safe_building_name


def process_payload(
    payload: Any,
    config_path: str | Path | None = None,
    log_level: str = "INFO",
) -> BatchOutput:
    settings = load_settings(config_path)
    logger = configure_logging(settings.output.root_dir / "logs", log_level)
    pipeline = WifiPdfPipeline(settings, logger)
    return pipeline.process_payload(payload)
