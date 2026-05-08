import type { Frame, Locator, Page } from "playwright";

import type { OmadaLan, OmadaMutationMode, OmadaPlan, OmadaSite, OmadaSsid, OmadaWlanGroup } from "../config/schema";
import type { RunReporter } from "../runtime/report";
import { clickFirstVisible, escapeRegex, fillFirstVisible, findFirstVisible, type QueryRoot } from "./locators";
import { isCloudLoginPage, recoverCloudLogin } from "./session";

interface ControllerApiEnvelope<T> {
  errorCode: number;
  msg?: string;
  result: T;
}

interface SiteDefaultsResponse {
  region?: string;
  timeZone?: string;
}

interface ScenarioOption {
  name?: string;
  isDefault?: boolean;
}

interface SiteListEntry {
  id: string;
  name: string;
}

interface LanNetworkEntry {
  id: string;
  name: string;
  vlan: number;
}

interface LanNetworksResponse {
  data?: LanNetworkEntry[];
}

interface WlanGroupEntry {
  id: string;
  name: string;
}

interface WlanGroupsResponse {
  data?: WlanGroupEntry[];
}

interface SsidEntry {
  id: string;
  name: string;
}

interface SsidListResponse {
  data?: SsidEntry[];
}

interface RateLimitProfileEntry {
  id: string;
  isDefault?: boolean;
  name?: string;
}

interface BrowserAppUtils {
  getToken?: () => string;
  getControllerIdUrl?: (path: string) => string;
  transferUrl?: (path: string) => string;
}

export class OmadaPortal {
  private readonly page: Page;
  private readonly reporter: RunReporter;
  private readonly controller: OmadaPlan["controller"];
  private siteDefaultsPromise: Promise<SiteDefaultsResponse> | null = null;
  private defaultScenarioPromise: Promise<string> | null = null;
  private currentSiteId: string | null = null;
  private readonly defaultRateLimitProfileIds = new Map<string, Promise<string>>();

  public constructor(page: Page, reporter: RunReporter, controller: OmadaPlan["controller"]) {
    this.page = page;
    this.reporter = reporter;
    this.controller = controller;
  }

  public async ensureOrganizationSelected(organizationName: string): Promise<void> {
    await this.page.goto(`${this.normalizedBaseUrl()}#orgManager`, { waitUntil: "domcontentloaded" });
    await this.waitForPortalLanding();
    await this.acceptCookiesIfVisible();
    await this.ensureStillAuthenticated();
    await this.waitForPortalLanding(60000);

    const existingFrame = this.getAppFrame();
    if (existingFrame?.url().includes("#dashboardGlobal")) {
      return;
    }

    if (existingFrame) {
      const shellText = await this.page.locator("body").innerText().catch(() => "");
      if (shellText.includes(organizationName)) {
        await this.page.goto(`${this.normalizedBaseUrl()}#dashboardGlobal`, { waitUntil: "domcontentloaded" });
        await this.settle();
        const redirectedFrame = this.getAppFrame();
        if (redirectedFrame) {
          return;
        }
      }
    }

    const searchBox = await findFirstVisible(this.page, [
      (root) => root.getByRole("textbox", { name: /Search Name/i }),
      (root) => root.getByPlaceholder(/Search Name/i),
    ]);

    if (searchBox) {
      await searchBox.fill("");
      await searchBox.fill(organizationName);
      const searchButton = await findFirstVisible(this.page, [
        (root) => root.getByRole("button", { name: /search/i }),
        (root) => root.getByText(/^search$/i),
      ]);
      if (searchButton) {
        await searchButton.click();
      }
      await this.settle();
    }

    const row = this.page.locator("tr[data-row-key]").filter({ hasText: new RegExp(escapeRegex(organizationName), "i") }).first();

    if (await row.isVisible({ timeout: 5000 }).catch(() => false)) {
      const action = row.locator(".table-action-container span.text-link").first();
      await action.click({ force: true });
      await this.waitForAppFrame("#dashboardGlobal", 30000);
      await this.settle();
      return;
    }

    const hydratedFrame = this.getAppFrame();
    if (hydratedFrame) {
      return;
    }

    const bodyText = (await this.page.locator("body").innerText().catch(() => "")).trim();
    if (bodyText.length === 0) {
      throw new Error("Omada portal did not finish loading before organization selection.");
    }

    if (!this.page.url().includes("id.tplinkcloud.com")) {
      return;
    }

    throw new Error(`Organization "${organizationName}" was not found in the Omada organization list.`);
  }

  public async ensureSite(site: OmadaSite): Promise<void> {
    await this.ensureSiteWithMode(site, "ensure");
  }

  public async openSite(siteName: string): Promise<void> {
    const site = await this.findSiteByName(siteName);
    if (!site) {
      throw new Error(`Site "${siteName}" was not found in the Omada controller list.`);
    }

    this.currentSiteId = site.id;
    await this.switchSiteViaApi(site.id);
    await this.waitForAppFrame("#dashboard", 15000);
    await this.settle();
  }

  public async ensureLan(lan: OmadaLan): Promise<void> {
    await this.ensureLanWithMode(lan, "ensure");
  }

  public async ensureWlanGroup(group: OmadaWlanGroup): Promise<void> {
    await this.ensureWlanGroupWithMode(group, "ensure");
  }

  public async ensureSsid(group: OmadaWlanGroup, ssid: OmadaSsid): Promise<void> {
    await this.ensureSsidWithMode(group, ssid, "ensure");
  }

  public async ensureSiteWithMode(site: OmadaSite, mutationMode: OmadaMutationMode): Promise<void> {
    await this.goToSitesSection();

    const existingSite = await this.findSiteByName(site.name);
    if (existingSite) {
      if (mutationMode === "create") {
        throw new Error(`Site "${site.name}" already exists, but mutationMode=create requires a new site.`);
      }
      this.reporter.log("info", `Site "${site.name}" already exists. Reusing it for mutationMode=${mutationMode}.`);
      return;
    }

    if (mutationMode === "update") {
      throw new Error(`Site "${site.name}" does not exist, but mutationMode=update requires an existing site.`);
    }

    const createdSiteId = await this.createSiteViaApi(site);
    this.reporter.log("success", `Created site "${site.name}" via the authenticated Essentials controller API (${createdSiteId}).`);
    await this.waitForSiteInControllerApi(site.name, 30000);
  }

  public async ensureLanWithMode(lan: OmadaLan, mutationMode: OmadaMutationMode): Promise<void> {
    const siteId = this.requireCurrentSiteId();
    const lanName = lan.name?.trim() ? lan.name.trim() : String(lan.vlanId);
    const existingLan = await this.findLanByNameOrVlan(siteId, lanName, lan.vlanId);

    if (existingLan) {
      if (mutationMode === "create") {
        throw new Error(`LAN "${lanName}" already exists, but mutationMode=create requires a new LAN.`);
      }

      if (mutationMode === "update" || mutationMode === "upsert") {
        const sameName = existingLan.name.toLowerCase() === lanName.toLowerCase();
        const sameVlan = existingLan.vlan === lan.vlanId;
        if (!sameName || !sameVlan) {
          throw new Error(
            `LAN "${lanName}" matched an existing LAN (${existingLan.name}, VLAN ${existingLan.vlan}), but in-place LAN mutation is not implemented yet.`,
          );
        }
      }

      this.reporter.log("info", `LAN "${lanName}" already exists. Reusing it for mutationMode=${mutationMode}.`);
      return;
    }

    if (mutationMode === "update") {
      throw new Error(`LAN "${lanName}" does not exist, but mutationMode=update requires an existing LAN.`);
    }

    await this.createLanViaApi(siteId, lanName, lan.vlanId);
    this.reporter.log("success", `Created LAN "${lanName}" on VLAN ${lan.vlanId}.`);
  }

  public async ensureWlanGroupWithMode(group: OmadaWlanGroup, mutationMode: OmadaMutationMode): Promise<void> {
    const siteId = this.requireCurrentSiteId();
    const existingGroup = await this.findWlanGroupByName(siteId, group.name);

    if (existingGroup) {
      if (mutationMode === "create") {
        throw new Error(`WLAN group "${group.name}" already exists, but mutationMode=create requires a new WLAN group.`);
      }

      this.reporter.log("info", `WLAN group "${group.name}" already exists. Reusing it for mutationMode=${mutationMode}.`);
      return;
    }

    if (mutationMode === "update") {
      throw new Error(`WLAN group "${group.name}" does not exist, but mutationMode=update requires an existing WLAN group.`);
    }

    await this.createWlanGroupViaApi(siteId, group.name);
    this.reporter.log("success", `Created WLAN group "${group.name}".`);
  }

  public async ensureSsidWithMode(group: OmadaWlanGroup, ssid: OmadaSsid, mutationMode: OmadaMutationMode): Promise<void> {
    const siteId = this.requireCurrentSiteId();
    const wlanGroup = await this.findWlanGroupByName(siteId, group.name);
    if (!wlanGroup) {
      throw new Error(`WLAN group "${group.name}" was not found after creation.`);
    }

    const existingSsid = await this.findSsidByName(siteId, wlanGroup.id, ssid.name);
    if (existingSsid) {
      if (mutationMode === "create") {
        throw new Error(`SSID "${ssid.name}" already exists, but mutationMode=create requires a new SSID.`);
      }

      if (mutationMode === "ensure") {
        this.reporter.log("info", `SSID "${ssid.name}" already exists. Skipping SSID creation.`);
        return;
      }

      await this.updateSsidViaApi(siteId, wlanGroup.id, existingSsid.id, ssid);
      this.reporter.log("success", `Updated SSID "${ssid.name}" in WLAN group "${group.name}".`);
      return;
    }

    if (mutationMode === "update") {
      throw new Error(`SSID "${ssid.name}" does not exist, but mutationMode=update requires an existing SSID.`);
    }

    const payload = await this.buildSsidPayload(siteId, ssid);
    const response = await this.callControllerApi<{ ssidId?: string }>(`/api/v2/sites/${siteId}/setting/wlans/${wlanGroup.id}/ssids`, {
      method: "POST",
      body: payload,
    });

    if (response.errorCode !== 0 || !response.result?.ssidId) {
      throw new Error(`Create SSID failed for "${ssid.name}": ${response.msg ?? "Unknown controller error."}`);
    }

    this.reporter.log("success", `Created SSID "${ssid.name}" in WLAN group "${group.name}".`);
  }

  public async listSites(searchKey?: string): Promise<Array<{ id: string; name: string }>> {
    const response = await this.callControllerApi<{ data?: SiteListEntry[] }>(
      `/api/v2/sites/basic?currentPageSize=200&currentPage=1&searchKey=${encodeURIComponent(searchKey ?? "")}`,
    );
    if (response.errorCode !== 0) {
      throw new Error(response.msg ?? "Unable to load Omada sites.");
    }

    return (response.result?.data ?? []).map((entry) => ({
      id: entry.id,
      name: entry.name,
    }));
  }

  public async getSiteById(siteId: string): Promise<{ id: string; name: string } | null> {
    const sites = await this.listSites();
    return sites.find((entry) => entry.id === siteId) ?? null;
  }

  public async listLanNetworksForSite(siteId: string): Promise<Array<{ id: string; name: string; vlan: number }>> {
    const networks = await this.listLanNetworks(siteId);
    return networks.map((entry) => ({
      id: entry.id,
      name: entry.name,
      vlan: entry.vlan,
    }));
  }

  public async listWlanGroupsForSite(siteId: string): Promise<Array<{ id: string; name: string }>> {
    const groups = await this.listWlanGroups(siteId);
    return groups.map((entry) => ({
      id: entry.id,
      name: entry.name,
    }));
  }

  public async listSsidsForGroup(siteId: string, wlanId: string): Promise<Array<{ id: string; name: string }>> {
    const ssids = await this.listSsids(siteId, wlanId);
    return ssids.map((entry) => ({
      id: entry.id,
      name: entry.name,
    }));
  }

  public async buildSiteSnapshot(siteName: string): Promise<{
    version: number;
    operation: string;
    source: string;
    passwordsAvailable: boolean;
    site: { id: string; name: string };
    lans: Array<{ id: string; name: string; vlan: number }>;
    wlanGroups: Array<{ id: string; name: string; ssids: Array<{ id: string; name: string; password: null }> }>;
  }> {
    const site = await this.findSiteByName(siteName);
    if (!site) {
      throw new Error(`Site "${siteName}" was not found when building the live snapshot.`);
    }

    const lans = await this.listLanNetworksForSite(site.id);
    const groups = await this.listWlanGroupsForSite(site.id);
    const wlanGroups: Array<{ id: string; name: string; ssids: Array<{ id: string; name: string; password: null }> }> = [];

    for (const group of groups) {
      const ssids = await this.listSsidsForGroup(site.id, group.id);
      wlanGroups.push({
        id: group.id,
        name: group.name,
        ssids: ssids.map((ssid) => ({
          id: ssid.id,
          name: ssid.name,
          password: null,
        })),
      });
    }

    return {
      version: 1,
      operation: "get",
      source: "live_omada",
      passwordsAvailable: false,
      site: {
        id: site.id,
        name: site.name,
      },
      lans,
      wlanGroups,
    };
  }

  private async goToSitesSection(): Promise<QueryRoot> {
    const existingFrame = this.getAppFrame();
    if (existingFrame?.url().includes("#dashboardGlobal")) {
      return existingFrame;
    }

    const orgRows = this.page.locator("tr[data-row-key]");
    const orgRow = orgRows.filter({ hasText: new RegExp(escapeRegex(this.controller.organizationName), "i") }).first();
    const fallbackRow = orgRows.first();
    const rowToUse = (await orgRow.count().catch(() => 0)) > 0 ? orgRow : fallbackRow;
    const orgRowCount = await this.waitForOrgRows();

    if (orgRowCount > 0) {
      await rowToUse.locator(".table-action-container span.text-link").first().click({ force: true });
      await this.waitForAppFrame("#dashboardGlobal", 30000);
      await this.settle();
      return await this.waitForAppFrame("#dashboardGlobal", 15000);
    }

    await this.page.goto(`${this.normalizedBaseUrl()}#dashboardGlobal`, { waitUntil: "domcontentloaded" });
    await this.settle();

    return await this.waitForAppFrame("#dashboardGlobal", 15000);
  }

  private async goToWiredNetworks(): Promise<QueryRoot> {
    const frame = await this.waitForAppFrame(undefined, 15000);
    await this.dispatchFrameNavigation(frame, "networkConfig");
    await this.dispatchFrameNavigation(frame, "wiredNetworksLan");
    await this.waitForAppFrame("#wiredNetworksLan", 15000);
    await this.settle();
    return frame;
  }

  private async goToWirelessNetworks(): Promise<QueryRoot> {
    const frame = await this.waitForAppFrame(undefined, 15000);
    await this.dispatchFrameNavigation(frame, "networkConfig");
    await this.dispatchFrameNavigation(frame, "WiFiNetworks");
    await this.waitForAppFrame("#WiFiNetworks", 15000);
    await this.settle();
    return frame;
  }

  private async openNavigationPath(segments: string[][]): Promise<void> {
    for (const labels of segments) {
      const visible = await this.hasVisible(this.page, labels.flatMap((label) => [
        (root: QueryRoot) => root.getByRole("link", { name: new RegExp(`^${escapeRegex(label)}$`, "i") }),
        (root: QueryRoot) => root.getByRole("menuitem", { name: new RegExp(`^${escapeRegex(label)}$`, "i") }),
        (root: QueryRoot) => root.getByText(new RegExp(`^${escapeRegex(label)}$`, "i")),
      ]));

      if (!visible) {
        continue;
      }

      await clickFirstVisible(this.page, labels.join(" / "), labels.flatMap((label) => [
        (root) => root.getByRole("link", { name: new RegExp(`^${escapeRegex(label)}$`, "i") }),
        (root) => root.getByRole("menuitem", { name: new RegExp(`^${escapeRegex(label)}$`, "i") }),
        (root) => root.getByText(new RegExp(`^${escapeRegex(label)}$`, "i")),
      ]), 4000);
      await this.settle();
    }
  }

  private async rowExists(name: string): Promise<boolean> {
    const root = await this.getPrimaryRoot();
    return this.hasVisible(root, [
      (surface) => surface.locator("tbody tr").filter({ hasText: new RegExp(escapeRegex(name), "i") }),
      (surface) => surface.locator(".simple-table-row,.ant-table-row").filter({ hasText: new RegExp(escapeRegex(name), "i") }),
      (surface) => surface.getByText(new RegExp(`^${escapeRegex(name)}$`, "i")),
    ], 2000);
  }

  private async getActiveSurface(): Promise<QueryRoot> {
    const root = await this.getPrimaryRoot();
    return (await findFirstVisible(root, [
      (root) => root.getByRole("dialog"),
      (root) => root.locator("[role='dialog']"),
      (root) => root.locator(".el-dialog"),
      (root) => root.locator(".ant-modal-content"),
    ], 1200)) ?? root;
  }

  private async acceptCookiesIfVisible(): Promise<void> {
    const agreeButton = await findFirstVisible(this.page, [
      (root) => root.getByRole("link", { name: /Agree/i }),
      (root) => root.getByRole("button", { name: /Agree/i }),
      (root) => root.getByText(/^Agree$/i),
    ], 800);

    if (agreeButton) {
      await agreeButton.click();
      await this.page.waitForTimeout(500);
    }
  }

  private async selectCombobox(root: QueryRoot, labels: string[], optionText: string): Promise<void> {
    const combobox = await findFirstVisible(root, labels.flatMap((label) => [
      (inner) => inner.getByLabel(new RegExp(escapeRegex(label), "i")),
      (inner) => inner.getByRole("combobox", { name: new RegExp(escapeRegex(label), "i") }),
      (inner) => inner.getByRole("button", { name: new RegExp(escapeRegex(label), "i") }),
    ]), 3000);

    if (!combobox) {
      throw new Error(`Dropdown for ${labels.join(" / ")} was not found.`);
    }

    await combobox.click();
    await this.page.waitForTimeout(400);

    await clickFirstVisible(this.page, `Option ${optionText}`, [
      (inner) => inner.getByRole("option", { name: new RegExp(`^${escapeRegex(optionText)}$`, "i") }),
      (inner) => inner.getByText(new RegExp(`^${escapeRegex(optionText)}$`, "i")),
      (inner) => inner.locator(`text=${optionText}`),
    ], 4000);
    await this.page.waitForTimeout(300);
  }

  private async trySelectCombobox(root: QueryRoot, labels: string[], optionText: string): Promise<void> {
    try {
      await this.selectCombobox(root, labels, optionText);
    } catch (error) {
      this.reporter.log("warning", `Skipped dropdown ${labels.join("/")} => ${optionText}: ${String(error)}`);
    }
  }

  private async tryFill(root: QueryRoot, description: string, value: string, candidates: Array<(root: QueryRoot) => Locator>): Promise<void> {
    try {
      await fillFirstVisible(root, description, value, candidates, 2000);
    } catch (error) {
      this.reporter.log("warning", `Skipped field ${description}: ${String(error)}`);
    }
  }

  private async hasVisible(root: QueryRoot, candidates: Array<(root: QueryRoot) => Locator>, timeoutMs = 1200): Promise<boolean> {
    return (await findFirstVisible(root, candidates, timeoutMs)) !== null;
  }

  private async createSiteViaApi(site: OmadaSite): Promise<string> {
    const defaults = await this.getSiteDefaults();
    const deviceAccount = site.deviceAccount ?? this.controller.deviceAccount;

    if (!deviceAccount) {
      throw new Error(`Site "${site.name}" is missing device-account credentials. Add controller.deviceAccount or sites[].deviceAccount to the plan file.`);
    }

    const payload: Record<string, unknown> = {
      name: site.name.trim(),
      region: site.region ?? defaults.region ?? "Canada",
      timeZone: site.timezone ?? defaults.timeZone ?? "America/New_York",
      scenario: site.scenario ?? await this.getDefaultScenarioName(),
      deviceAccountSetting: {
        username: deviceAccount.username,
        password: deviceAccount.password,
      },
      supportL2: true,
      tagIds: [],
      type: 0,
    };

    const response = await this.callControllerApi<{ siteId?: string }>("/api/v2/sites", {
      method: "POST",
      body: payload,
    });

    if (response.errorCode !== 0 || !response.result?.siteId) {
      throw new Error(`Create site failed for "${site.name}": ${response.msg ?? "Unknown controller error."}`);
    }

    return response.result.siteId;
  }

  private async getSiteDefaults(): Promise<SiteDefaultsResponse> {
    if (!this.siteDefaultsPromise) {
      this.siteDefaultsPromise = this.callControllerApi<SiteDefaultsResponse>("/api/v2/controller/site-setting")
        .then((response) => {
          if (response.errorCode !== 0) {
            throw new Error(response.msg ?? "Unable to load Omada site defaults.");
          }
          return response.result ?? {};
        });
    }

    return this.siteDefaultsPromise;
  }

  private async getDefaultScenarioName(): Promise<string> {
    if (!this.defaultScenarioPromise) {
      this.defaultScenarioPromise = this.callControllerApi<Array<string | ScenarioOption>>("/api/v2/scenarios/difference")
        .then((response) => {
          if (response.errorCode !== 0) {
            throw new Error(response.msg ?? "Unable to load Omada scenarios.");
          }

          const scenarios = response.result ?? [];
          const objectEntries = scenarios.filter((entry): entry is ScenarioOption => typeof entry === "object" && entry !== null);
          const defaultEntry = objectEntries.find((entry) => entry.isDefault);
          if (defaultEntry?.name) {
            return defaultEntry.name;
          }

          const firstNamedEntry = objectEntries.find((entry) => Boolean(entry.name));
          if (firstNamedEntry?.name) {
            return firstNamedEntry.name;
          }

          const firstStringEntry = scenarios.find((entry) => typeof entry === "string");
          if (typeof firstStringEntry === "string" && firstStringEntry.length > 0) {
            return firstStringEntry;
          }

          return "Multi";
        });
    }

    return this.defaultScenarioPromise;
  }

  private async findSiteByName(siteName: string): Promise<SiteListEntry | null> {
    const encodedSiteName = encodeURIComponent(siteName);
    const response = await this.callControllerApi<{ data?: SiteListEntry[] }>(`/api/v2/sites/basic?currentPageSize=10&currentPage=1&searchKey=${encodedSiteName}`);
    if (response.errorCode !== 0) {
      throw new Error(response.msg ?? `Unable to search for site "${siteName}".`);
    }

    const sites = response.result?.data ?? [];
    return sites.find((entry) => entry.name.toLowerCase() === siteName.toLowerCase()) ?? null;
  }

  private async listLanNetworks(siteId: string): Promise<LanNetworkEntry[]> {
    const response = await this.callControllerApi<LanNetworksResponse>(`/api/v2/sites/${siteId}/setting/lan/networks?currentPage=1&currentPageSize=200`);
    if (response.errorCode !== 0) {
      throw new Error(response.msg ?? "Unable to load LAN networks.");
    }

    return response.result?.data ?? [];
  }

  private async findLanByNameOrVlan(siteId: string, name: string, vlanId: number): Promise<LanNetworkEntry | null> {
    const networks = await this.listLanNetworks(siteId);
    return networks.find((entry) => entry.name.toLowerCase() === name.toLowerCase() || entry.vlan === vlanId) ?? null;
  }

  private async createLanViaApi(siteId: string, name: string, vlanId: number): Promise<void> {
    const payload = {
      deviceConfig: {
        portIsolationEnable: false,
        flowControlEnable: false,
        deviceList: [],
        tagIds: [],
      },
      lanNetwork: {
        name,
        deviceType: 3,
        vlanType: 0,
        vlan: vlanId,
        upnpLanEnable: false,
        igmpSnoopEnable: false,
        dhcpGuard: {
          enable: false,
        },
        dhcpv6Guard: {
          enable: false,
        },
        qosQueueEnable: false,
        mldSnoopEnable: false,
        dhcpL2RelayEnable: false,
      },
    };

    const checkResponse = await this.callControllerApi<undefined>(`/openapi/v1/sites/${siteId}/networks/check`, {
      method: "POST",
      body: payload,
    });
    if (checkResponse.errorCode !== 0) {
      throw new Error(checkResponse.msg ?? `LAN validation failed for VLAN ${vlanId}.`);
    }

    const confirmResponse = await this.callControllerApi<{ networkIdList?: string[] }>(`/openapi/v1/sites/${siteId}/networks/confirm`, {
      method: "POST",
      body: payload,
    });
    if (confirmResponse.errorCode !== 0 || (confirmResponse.result?.networkIdList?.length ?? 0) === 0) {
      throw new Error(confirmResponse.msg ?? `LAN creation failed for VLAN ${vlanId}.`);
    }
  }

  private async listWlanGroups(siteId: string): Promise<WlanGroupEntry[]> {
    const response = await this.callControllerApi<WlanGroupsResponse>(`/api/v2/sites/${siteId}/setting/wlans`);
    if (response.errorCode !== 0) {
      throw new Error(response.msg ?? "Unable to load WLAN groups.");
    }

    return response.result?.data ?? [];
  }

  private async findWlanGroupByName(siteId: string, name: string): Promise<WlanGroupEntry | null> {
    const groups = await this.listWlanGroups(siteId);
    return groups.find((entry) => entry.name.toLowerCase() === name.toLowerCase()) ?? null;
  }

  private async createWlanGroupViaApi(siteId: string, name: string): Promise<void> {
    const response = await this.callControllerApi<{ wlanId?: string }>(`/api/v2/sites/${siteId}/setting/wlans`, {
      method: "POST",
      body: {
        name,
        clone: false,
      },
    });

    if (response.errorCode !== 0 || !response.result?.wlanId) {
      throw new Error(response.msg ?? `Unable to create WLAN group "${name}".`);
    }
  }

  private async listSsids(siteId: string, wlanId: string): Promise<SsidEntry[]> {
    const response = await this.callControllerApi<SsidListResponse>(`/api/v2/sites/${siteId}/setting/wlans/${wlanId}/ssids?currentPage=1&currentPageSize=200`);
    if (response.errorCode !== 0) {
      throw new Error(response.msg ?? `Unable to load SSIDs for WLAN group ${wlanId}.`);
    }

    return response.result?.data ?? [];
  }

  private async findSsidByName(siteId: string, wlanId: string, name: string): Promise<SsidEntry | null> {
    const ssids = await this.listSsids(siteId, wlanId);
    return ssids.find((entry) => entry.name.toLowerCase() === name.toLowerCase()) ?? null;
  }

  private async updateSsidViaApi(siteId: string, wlanId: string, ssidId: string, ssid: OmadaSsid): Promise<void> {
    const payload = await this.buildSsidPayload(siteId, ssid);
    const response = await this.callControllerApi<undefined>(`/api/v2/sites/${siteId}/setting/wlans/${wlanId}/ssids/${ssidId}`, {
      method: "PATCH",
      body: payload,
    });

    if (response.errorCode !== 0) {
      throw new Error(`Modify SSID failed for "${ssid.name}": ${response.msg ?? "Unknown controller error."}`);
    }
  }

  private async getDefaultRateLimitProfileId(siteId: string): Promise<string> {
    const cached = this.defaultRateLimitProfileIds.get(siteId);
    if (cached) {
      return cached;
    }

    const promise = this.callControllerApi<RateLimitProfileEntry[]>(`/api/v2/sites/${siteId}/setting/profiles/rateLimits?currentPage=1&currentPageSize=200`)
      .then((response) => {
        if (response.errorCode !== 0) {
          throw new Error(response.msg ?? "Unable to load rate-limit profiles.");
        }

        const profiles = Array.isArray(response.result) ? response.result : [];
        const defaultProfile = profiles.find((profile) => profile.isDefault) ?? profiles.find((profile) => profile.name === "Default");
        if (!defaultProfile?.id) {
          throw new Error("Default rate-limit profile was not found for the current site.");
        }

        return defaultProfile.id;
      });

    this.defaultRateLimitProfileIds.set(siteId, promise);
    return promise;
  }

  private async resolveLanNetworkByVlan(siteId: string, vlanId: number): Promise<LanNetworkEntry> {
    const networks = await this.listLanNetworks(siteId);
    const network = networks.find((entry) => entry.vlan === vlanId);
    if (!network) {
      throw new Error(`LAN for VLAN ${vlanId} was not found in the current site.`);
    }

    return network;
  }

  private async buildSsidPayload(siteId: string, ssid: OmadaSsid): Promise<Record<string, unknown>> {
    if (ssid.security !== "wpa2_psk") {
      throw new Error(`SSID "${ssid.name}" requested unsupported security "${ssid.security}". Only wpa2_psk is implemented in the controller-backed flow.`);
    }

    if (!ssid.password) {
      throw new Error(`SSID "${ssid.name}" is missing a password.`);
    }

    const rateLimitId = await this.getDefaultRateLimitProfileId(siteId);
    const mappedLan = typeof ssid.vlanId === "number" ? await this.resolveLanNetworkByVlan(siteId, ssid.vlanId) : null;

    return {
      name: ssid.name,
      band: 3,
      type: 0,
      guestNetEnable: false,
      security: 3,
      broadcast: !ssid.hideSsid,
      vlanEnable: Boolean(mappedLan),
      vlanSetting: mappedLan
        ? {
            mode: 1,
            customConfig: {
              mode: 0,
              lanNetworkId: mappedLan.id,
            },
          }
        : {
            mode: 0,
            customConfig: {},
          },
      pskSetting: {
        securityKey: ssid.password,
        encryptionPsk: 3,
        versionPsk: 2,
        gikRekeyPskEnable: false,
      },
      rateLimit: {
        rateLimitId,
        downLimitEnable: false,
        upLimitEnable: false,
      },
      ssidRateLimit: {
        rateLimitId,
        downLimitEnable: false,
        upLimitEnable: false,
      },
      wlanScheduleEnable: false,
      rateAndBeaconCtrl: {
        manageRateControl2gEnable: false,
        manageRateControl5gEnable: false,
        rate2gCtrlEnable: false,
        rate5gCtrlEnable: false,
        rate6gCtrlEnable: false,
      },
      macFilterEnable: false,
      wlanId: "",
      enable11r: false,
      pmfMode: 3,
      multiCastSetting: {
        multiCastEnable: true,
        arpCastEnable: true,
        filterEnable: false,
        ipv6CastEnable: true,
        channelUtil: 100,
      },
      wpaPsk: [2, 3],
      deviceType: 1,
      prohibitWifiShare: false,
      mloEnable: false,
      accessEnable: false,
      portalEnable: false,
    };
  }

  private async switchSiteViaApi(siteId: string): Promise<void> {
    const response = await this.callControllerApi<undefined>(`/api/v2/sites/${siteId}/cmd/switch`, { method: "POST" });
    if (response.errorCode !== 0) {
      throw new Error(response.msg ?? `Unable to switch to site ${siteId}.`);
    }

    const frame = await this.waitForAppFrame(undefined, 15000);
    await frame.evaluate(() => {
      location.hash = "#dashboard";
    });
  }

  private async callControllerApi<T>(
    path: string,
    options: { method?: "GET" | "POST" | "PATCH"; body?: unknown } = {},
  ): Promise<ControllerApiEnvelope<T>> {
    const frame = await this.waitForAppFrame(undefined, 15000);
    const response = await frame.evaluate(async ({ path, method, body }) => {
      const browserGlobal = globalThis as typeof globalThis & { $?: { appUtils?: BrowserAppUtils } };
      const appUtils = browserGlobal.$?.appUtils;
      if (!appUtils?.getToken || !appUtils?.getControllerIdUrl || !appUtils?.transferUrl) {
        throw new Error("Omada controller helpers were not available in the current app frame.");
      }

      const controllerPath = appUtils.getControllerIdUrl(path);
      const url = appUtils.transferUrl(controllerPath);
      const headers: Record<string, string> = {
        accept: "application/json, text/plain, */*",
        "csrf-token": appUtils.getToken(),
        "omada-request-source": "web-local",
        refresh: "manual",
        "x-requested-with": "XMLHttpRequest",
      };

      if (body !== undefined) {
        headers["content-type"] = "application/json; charset=UTF-8";
      }

      const requestInit: RequestInit = {
        method,
        credentials: "include",
        headers,
      };
      if (body !== undefined) {
        requestInit.body = JSON.stringify(body);
      }

      const result = await fetch(url, requestInit);

      const text = await result.text();
      let parsed: unknown;
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = undefined;
      }

      return {
        ok: result.ok,
        status: result.status,
        text,
        parsed,
      };
    }, {
      path,
      method: options.method ?? (options.body === undefined ? "GET" : "POST"),
      body: options.body,
    });

    if (!response.ok) {
      throw new Error(`Controller API ${path} failed with HTTP ${response.status}: ${response.text}`);
    }

    if (!response.parsed) {
      throw new Error(`Controller API ${path} returned a non-JSON response: ${response.text}`);
    }

    return response.parsed as ControllerApiEnvelope<T>;
  }

  private async waitForSiteInControllerApi(siteName: string, timeoutMs = 30000): Promise<void> {
    const startedAt = Date.now();

    while (Date.now() - startedAt < timeoutMs) {
      if (await this.findSiteByName(siteName)) {
        return;
      }
      await this.page.waitForTimeout(800);
    }

    throw new Error(`Created site "${siteName}" did not appear in the Omada controller list within ${timeoutMs}ms.`);
  }

  private async waitForCreateCompletion(): Promise<void> {
    await this.page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => undefined);
    await this.waitForBlockingUiToClear();
    await this.page.waitForTimeout(1200);
  }

  private async waitForPortalLanding(timeoutMs = 25000): Promise<void> {
    const startedAt = Date.now();

    while (Date.now() - startedAt < timeoutMs) {
      if (await isCloudLoginPage(this.page)) {
        return;
      }

      if (this.getAppFrame()) {
        return;
      }

      const orgRowCount = await this.page.locator("tr[data-row-key]").count().catch(() => 0);
      if (orgRowCount > 0) {
        return;
      }

      const bodyText = (await this.page.locator("body").innerText().catch(() => "")).trim();
      if (bodyText.length > 0 && /sign in|organization|search name/i.test(bodyText)) {
        return;
      }

      await this.page.waitForTimeout(500);
    }
  }

  private async ensureStillAuthenticated(): Promise<void> {
    if (this.page.url().includes("id.tplinkcloud.com") || await isCloudLoginPage(this.page)) {
      this.reporter.log("warning", "Omada session expired. Attempting automatic cloud re-login.");
      const recovered = await recoverCloudLogin(this.page, this.controller).catch((error) => {
        this.reporter.log("error", `Automatic cloud re-login failed: ${String(error)}`);
        return false;
      });
      if (recovered) {
        this.reporter.log("success", "Recovered Omada cloud session automatically.");
        return;
      }
      throw new Error("Omada session expired and automatic cloud re-login failed.");
    }
  }

  private mapSecurity(security: OmadaSsid["security"]): string {
    switch (security) {
      case "wpa3_sae":
        return "WPA-Personal";
      case "open":
        return "Open";
      case "wpa2_psk":
      default:
        return "WPA-Personal";
    }
  }

  private requireCurrentSiteId(): string {
    if (!this.currentSiteId) {
      throw new Error("No Omada site is currently selected. Open the site before applying LAN, WLAN group, or SSID changes.");
    }

    return this.currentSiteId;
  }

  private normalizedBaseUrl(): string {
    return this.controller.baseUrl.endsWith("/") ? this.controller.baseUrl : `${this.controller.baseUrl}/`;
  }

  private async settle(): Promise<void> {
    await this.page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => undefined);
    await this.waitForBlockingUiToClear();
    await this.page.waitForTimeout(900);
    await this.ensureStillAuthenticated();
  }

  private getAppFrame(): Frame | null {
    return this.page.frames().find((frame) => frame.url().includes("/essential/index.html")) ?? null;
  }

  private async getPrimaryRoot(): Promise<QueryRoot> {
    return this.getAppFrame() ?? this.page;
  }

  private async waitForAppFrame(hashFragment?: string, timeoutMs = 15000): Promise<Frame> {
    const start = Date.now();

    while (Date.now() - start < timeoutMs) {
      const frame = this.getAppFrame();
      if (!frame) {
        await this.page.waitForTimeout(500);
        continue;
      }

      if (!hashFragment || frame.url().includes(hashFragment)) {
        return frame;
      }

      await this.page.waitForTimeout(500);
    }

    throw new Error(`Omada application frame ${hashFragment ?? ""} was not ready.`);
  }

  private async dispatchFrameNavigation(frame: Frame, naviValue: string): Promise<void> {
    const clicked = await frame.locator(`li[navi-value="${naviValue}"] > a`).evaluate((el) => {
      el.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
      el.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
      el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
      el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
      el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      return true;
    }).catch(() => false);

    if (!clicked) {
      throw new Error(`Navigation item "${naviValue}" was not available in the current Omada site frame.`);
    }
  }

  private async getSelectedWlanGroupName(root: QueryRoot): Promise<string | null> {
    const selected = await findFirstVisible(root, [
      (surface) => surface.locator(".wlan-group-select .ant-select-selection-item"),
      (surface) => surface.locator(".ant-select-selection-item"),
    ], 1500);

    if (!selected) {
      return null;
    }

    return (await selected.innerText().catch(() => "")).trim() || null;
  }

  private async trySelectExistingWlanGroup(root: QueryRoot, groupName: string): Promise<boolean> {
    const selector = await findFirstVisible(root, [
      (surface) => surface.locator(".wlan-group-select .ant-select-selector"),
      (surface) => surface.getByLabel(/WLAN Group/i),
      (surface) => surface.getByRole("combobox", { name: /WLAN Group/i }),
    ], 3000);

    if (!selector) {
      return false;
    }

    await selector.click();
    await this.page.waitForTimeout(500);

    const option = await findFirstVisible(this.page, [
      (surface) => surface.getByRole("option", { name: new RegExp(`^${escapeRegex(groupName)}$`, "i") }),
      (surface) => surface.locator(".ant-select-item-option").filter({ hasText: new RegExp(`^${escapeRegex(groupName)}$`, "i") }),
      (surface) => surface.getByText(new RegExp(`^${escapeRegex(groupName)}$`, "i")),
    ], 2000);

    if (!option) {
      await this.page.keyboard.press("Escape").catch(() => undefined);
      return false;
    }

    await option.click({ force: true });
    await this.settle();
    return true;
  }

  private async advanceWizard(root: QueryRoot, labels: string[]): Promise<void> {
    for (const label of labels) {
      const button = await findFirstVisible(root, [
        (surface) => surface.getByRole("button", { name: new RegExp(`^${escapeRegex(label)}$`, "i") }),
        (surface) => surface.getByText(new RegExp(`^${escapeRegex(label)}$`, "i")),
      ], 1500);

      if (!button) {
        continue;
      }

      await button.click({ force: true });
      await this.waitForCreateCompletion();
    }
  }

  private formatGatewayWithSubnet(gateway?: string, subnetMask?: string): string | null {
    if (!gateway || !subnetMask) {
      return null;
    }

    const prefix = this.subnetMaskToPrefix(subnetMask);
    return prefix === null ? null : `${gateway}/${prefix}`;
  }

  private subnetMaskToPrefix(subnetMask: string): number | null {
    const octets = subnetMask.split(".").map((value) => Number(value));
    if (octets.length !== 4 || octets.some((value) => Number.isNaN(value) || value < 0 || value > 255)) {
      return null;
    }

    const bitString = octets.map((value) => value.toString(2).padStart(8, "0")).join("");
    if (!/^1*0*$/.test(bitString)) {
      return null;
    }

    return bitString.indexOf("0") === -1 ? 32 : bitString.indexOf("0");
  }

  private async waitForBlockingUiToClear(): Promise<void> {
    await this.page.waitForFunction(() => {
      const blockers = [".ant-drawer-mask", ".cloud-progress-bar", "#preload-progress-container", ".ant-spin-blur"];

      return blockers.every((selector) => {
        return Array.from(document.querySelectorAll(selector)).every((element) => {
          const style = window.getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return style.display === "none"
            || style.visibility === "hidden"
            || style.opacity === "0"
            || rect.width === 0
            || rect.height === 0;
        });
      });
    }, { timeout: 10000 }).catch(() => undefined);
  }

  private async waitForOrgRows(timeoutMs = 8000): Promise<number> {
    const startedAt = Date.now();

    while (Date.now() - startedAt < timeoutMs) {
      const count = await this.page.locator("tr[data-row-key]").count().catch(() => 0);
      if (count > 0) {
        return count;
      }
      await this.page.waitForTimeout(400);
    }

    return 0;
  }
}
