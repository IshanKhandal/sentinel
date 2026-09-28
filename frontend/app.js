/**
 * Sentinel Gujarat — Tactical Command Center Single Page Application Engine
 * Protocol Standards: docs/engineering-rules.md, docs/demo-mode.md, docs/realtime-contract.md
 */

const App = {
  state: {
    token: sessionStorage.getItem("sentinel_token") || null,
    user: null,
    operationMode: "DEMO",
    cameras: [],
    unmappedCameras: [],
    detections: [],
    alerts: [],
    watchlists: [],
    investigations: [],
    currentPlateHistory: null,
    activeView: "overview",
    ws: null,
    wsReconnectTimer: null,
    wsHeartbeatTimer: null,
    map: null,
    mapMarkers: {},
    routePolyline: null,
    wsEventCount: 0,
  },

  // ------------------------------------------------------------------------
  // 1. API Client with JWT Bearer Interceptor & Error Handling
  // ------------------------------------------------------------------------
  api: {
    async request(endpoint, options = {}) {
      const headers = options.headers || {};
      if (App.state.token) {
        headers["Authorization"] = `Bearer ${App.state.token}`;
      }
      if (options.body && typeof options.body === "object" && !(options.body instanceof FormData)) {
        headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(options.body);
      }
      options.headers = headers;

      try {
        const response = await fetch(endpoint, options);
        if (response.status === 401) {
          // Token expired or invalid
          App.state.token = null;
          sessionStorage.removeItem("sentinel_token");
          App.ui.updateAuthUI();
          App.ui.showToast("Session expired or unauthorized. Please authenticate.", "error");
          App.ui.showLoginModal();
          throw new Error("Unauthorized (401)");
        }
        if (response.status === 403) {
          const errData = await response.json().catch(() => ({ detail: "Clearance forbidden" }));
          App.ui.showToast(`Access Denied: ${errData.detail || "Insufficient RBAC clearance"}`, "error");
          throw new Error(`Forbidden: ${errData.detail}`);
        }
        if (!response.ok) {
          const errText = await response.text();
          throw new Error(`HTTP ${response.status}: ${errText}`);
        }
        if (response.status === 204) {
          return null;
        }
        return await response.json();
      } catch (err) {
        console.error(`API Error [${endpoint}]:`, err);
        throw err;
      }
    },

    get(url) { return this.request(url, { method: "GET" }); },
    post(url, body) { return this.request(url, { method: "POST", body }); },
    patch(url, body) { return this.request(url, { method: "PATCH", body }); },
    delete(url) { return this.request(url, { method: "DELETE" }); },
  },

  // ------------------------------------------------------------------------
  // 2. Authentication & Session Manager (Stage 15 RBAC)
  // ------------------------------------------------------------------------
  auth: {
    async init() {
      // Check health & operation mode
      try {
        const health = await App.api.get("/health");
        App.state.operationMode = health.operation_mode || "DEMO";
        const modeBadge = document.getElementById("operation-mode-badge");
        const modeText = document.getElementById("operation-mode-text");
        if (App.state.operationMode === "LIVE") {
          modeBadge.className = "badge-pill mode-live";
          modeText.textContent = "LIVE SYSTEM";
        } else {
          modeBadge.className = "badge-pill mode-demo";
          modeText.textContent = "DEMO MODE";
        }
        document.getElementById("footer-version").textContent = health.app_version || "v1.0.0";
      } catch (e) {
        console.warn("Could not fetch system health:", e);
      }

      // Check stored JWT token
      if (App.state.token) {
        try {
          const user = await App.api.get("/api/v1/auth/me");
          App.state.user = user;
          App.ui.updateAuthUI();
          App.ws.connect();
        } catch (e) {
          App.state.token = null;
          sessionStorage.removeItem("sentinel_token");
          App.ui.updateAuthUI();
        }
      } else {
        App.ui.updateAuthUI();
      }
    },

    quickFill(username, password) {
      document.getElementById("login-username").value = username;
      document.getElementById("login-password").value = password;
      this.submitLogin();
    },

    async submitLogin() {
      const uField = document.getElementById("login-username");
      const pField = document.getElementById("login-password");
      const errAlert = document.getElementById("login-error-alert");
      errAlert.style.display = "none";

      const username = uField.value.trim();
      const password = pField.value;
      if (!username || !password) {
        errAlert.textContent = "Please provide both badge identifier and password.";
        errAlert.style.display = "block";
        return;
      }

      try {
        const res = await App.api.post("/api/v1/auth/login", { username, password });
        App.state.token = res.access_token;
        sessionStorage.setItem("sentinel_token", res.access_token);
        
        // Fetch detailed profile
        const user = await App.api.get("/api/v1/auth/me");
        App.state.user = user;
        
        App.ui.updateAuthUI();
        App.ui.hideModal("modal-login");
        App.ui.showToast(`Authenticated: ${user.full_name} (${user.role})`, "success");
        
        // Connect WebSocket with new token
        App.ws.connect();

        // Refresh current active view
        App.nav.reloadCurrentView();
      } catch (err) {
        errAlert.textContent = err.message || "Authentication failed. Check credentials.";
        errAlert.style.display = "block";
      }
    },

    async logout() {
      if (App.state.token) {
        try {
          await App.api.post("/api/v1/auth/logout", {});
        } catch (e) {
          // Ignore logout api errors on client cleanup
        }
      }
      App.state.token = null;
      App.state.user = null;
      sessionStorage.removeItem("sentinel_token");
      App.ws.disconnect();
      App.ui.updateAuthUI();
      App.ui.showToast("Officer logged out successfully.", "info");
      App.nav.switchView("overview");
    },

    hasPermission(perm) {
      if (!App.state.user) return false;
      if (App.state.user.role === "SuperAdmin") return true;
      const perms = App.state.user.permissions || [];
      return perms.includes(perm);
    },
  },

  // ------------------------------------------------------------------------
  // 3. Realtime WebSocket Gateway (Stage 14 Integration)
  // ------------------------------------------------------------------------
  ws: {
    connect() {
      this.disconnect();
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const host = window.location.host;
      let wsUrl = `${protocol}//${host}/api/v1/ws/live`;
      if (App.state.token) {
        wsUrl += `?token=${encodeURIComponent(App.state.token)}`;
      }

      try {
        App.state.ws = new WebSocket(wsUrl);

        App.state.ws.onopen = () => {
          this.setConnectedUI(true);
          // Subscribe to standard tactical broadcast channels
          App.state.ws.send(JSON.stringify({
            action: "subscribe",
            topics: ["all"],
          }));

          // Heartbeat ping every 25 seconds
          App.state.wsHeartbeatTimer = setInterval(() => {
            if (App.state.ws && App.state.ws.readyState === WebSocket.OPEN) {
              App.state.ws.send(JSON.stringify({ type: "ping" }));
            }
          }, 25000);
        };

        App.state.ws.onmessage = (event) => {
          App.state.wsEventCount++;
          const statCounter = document.getElementById("stat-ws-events");
          if (statCounter) statCounter.textContent = App.state.wsEventCount;

          try {
            const data = JSON.parse(event.data);
            this.handleEvent(data);
          } catch (e) {
            console.warn("WS Parse Error:", e);
          }
        };

        App.state.ws.onclose = (event) => {
          this.setConnectedUI(false);
          this.cleanup();
          // Auto reconnect if not closed by user
          if (App.state.token && !App.state.wsReconnectTimer) {
            App.state.wsReconnectTimer = setTimeout(() => {
              App.state.wsReconnectTimer = null;
              this.connect();
            }, 5000);
          }
        };

        App.state.ws.onerror = (err) => {
          console.warn("WebSocket transport error:", err);
        };
      } catch (err) {
        console.error("Failed to initialize WebSocket:", err);
      }
    },

    disconnect() {
      this.cleanup();
      if (App.state.ws) {
        App.state.ws.close();
        App.state.ws = null;
      }
      this.setConnectedUI(false);
    },

    cleanup() {
      if (App.state.wsHeartbeatTimer) {
        clearInterval(App.state.wsHeartbeatTimer);
        App.state.wsHeartbeatTimer = null;
      }
      if (App.state.wsReconnectTimer) {
        clearTimeout(App.state.wsReconnectTimer);
        App.state.wsReconnectTimer = null;
      }
    },

    setConnectedUI(connected) {
      const badge = document.getElementById("ws-status-badge");
      const text = document.getElementById("ws-status-text");
      if (connected) {
        badge.className = "badge-pill ws-connected";
        text.textContent = "WS LIVE";
      } else {
        badge.className = "badge-pill ws-disconnected";
        text.textContent = "WS DISCONNECTED";
      }
    },

    handleEvent(msg) {
      if (msg.type === "pong") return;

      const eventType = msg.event_type || msg.type;
      
      // 1. Detection Event
      if (eventType === "detection.vehicle" || eventType === "anpr.plate_read") {
        const payload = msg.payload || {};
        App.ui.showToast(`Vehicle Observed: ${payload.plate_number || "ANPR"}`, "info");
        // Prepend to detections view if loaded
        App.detections.prependLive(payload);
      }

      // 2. Alert Triggered
      if (eventType === "alert.watchlist_match" || eventType === "alert.created") {
        const payload = msg.payload || {};
        App.ui.showToast(`HOTLIST MATCH: ${payload.plate_number} (${payload.severity || "CRITICAL"})`, "critical");
        App.alerts.incrementBadge();
        App.alerts.prependLive(payload);
      }

      // 3. Investigation Event
      if (eventType === "investigation.created" || eventType === "investigation.event_attached") {
        App.investigations.load();
      }
    },
  },

  // ------------------------------------------------------------------------
  // 4. View & Navigation Controller
  // ------------------------------------------------------------------------
  nav: {
    switchView(viewName) {
      App.state.activeView = viewName;

      // Update Sidebar active state
      document.querySelectorAll(".nav-item").forEach((item) => {
        if (item.getAttribute("data-view") === viewName) {
          item.classList.add("active");
        } else {
          item.classList.remove("active");
        }
      });

      // Update View Panes
      document.querySelectorAll(".view-pane").forEach((pane) => {
        pane.classList.remove("active");
      });
      const targetPane = document.getElementById(`view-view-${viewName}`) || document.getElementById(`view-${viewName}`);
      if (targetPane) {
        targetPane.classList.add("active");
      }

      // Trigger lazy data load for the view
      this.reloadCurrentView();
    },

    reloadCurrentView() {
      const v = App.state.activeView;
      if (v === "overview") App.dashboard.refresh();
      else if (v === "cameras") App.cameras.load();
      else if (v === "gis") App.gis.load();
      else if (v === "vehicles") { /* vehicle view searches on demand */ }
      else if (v === "detections") App.detections.load();
      else if (v === "watchlists") App.watchlists.load();
      else if (v === "alerts") App.alerts.load();
      else if (v === "investigations") App.investigations.load();
      else if (v === "audit") App.audit.load();
      else if (v === "users") App.users.load();
    },
  },

  // ------------------------------------------------------------------------
  // 5. Tactical Dashboard Overview (Stage 5)
  // ------------------------------------------------------------------------
  dashboard: {
    async refresh() {
      // 1. Fetch Cameras count
      try {
        const cameras = await App.api.get("/api/v1/cameras");
        App.state.cameras = cameras;
        const onlineCount = cameras.filter((c) => c.status === "ONLINE").length;
        const offlineCount = cameras.length - onlineCount;
        document.getElementById("stat-cameras-total").textContent = cameras.length;
        document.getElementById("stat-cameras-online").textContent = onlineCount;
        document.getElementById("stat-cameras-offline").textContent = offlineCount;
      } catch (e) {
        document.getElementById("stat-cameras-total").textContent = "N/A";
      }

      // 2. Fetch Detections
      try {
        const detRes = await App.api.get("/api/v1/detections?limit=5");
        const items = detRes.items || detRes || [];
        document.getElementById("stat-detections-total").textContent = detRes.total !== undefined ? detRes.total : items.length;
        
        // Render Recent Detections Table
        const tbody = document.getElementById("overview-detections-tbody");
        if (items.length === 0) {
          tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-subtle);">No vehicle detections recorded.</td></tr>';
        } else {
          tbody.innerHTML = items.map((d) => `
            <tr>
              <td><span class="plate-badge">${d.plate_number || "NO PLATE"}</span></td>
              <td style="text-transform: capitalize;">${d.vehicle_type || "Vehicle"}</td>
              <td>
                <div class="confidence-bar">
                  <div class="confidence-fill"><div class="confidence-fill-inner" style="width: ${Math.round((d.confidence_plate || 0.9) * 100)}%;"></div></div>
                  <span>${Math.round((d.confidence_plate || 0.9) * 100)}%</span>
                </div>
              </td>
              <td>${d.camera_name || d.camera_id?.slice(0, 8) || "Node"}</td>
              <td style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">${App.ui.formatTime(d.detected_at)}</td>
            </tr>
          `).join("");
        }
      } catch (e) {
        document.getElementById("stat-detections-total").textContent = "N/A";
      }

      // 3. Fetch Alerts
      try {
        const alertsRes = await App.api.get("/api/v1/alerts?limit=5");
        const alertItems = alertsRes.items || alertsRes || [];
        const activeAlerts = alertItems.filter((a) => a.status === "NEW" || a.status === "ACKNOWLEDGED");
        document.getElementById("stat-alerts-active").textContent = activeAlerts.length;

        const tbody = document.getElementById("overview-alerts-tbody");
        if (alertItems.length === 0) {
          tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-subtle);">No active incident alerts.</td></tr>';
        } else {
          tbody.innerHTML = alertItems.map((a) => `
            <tr>
              <td><span class="plate-badge" style="border-color: var(--sev-critical);">${a.plate_number}</span></td>
              <td><span class="badge-pill" style="background: rgba(239, 68, 68, 0.2); color: var(--sev-critical); font-size: 9px;">${a.severity}</span></td>
              <td>${a.camera_id ? a.camera_id.slice(0, 8) : "Sector Cam"}</td>
              <td style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">${App.ui.formatTime(a.created_at)}</td>
              <td>
                <button class="btn-primary" style="padding: 2px 8px; font-size: 10px;" onclick="App.alerts.acknowledge('${a.id}')">Acknowledge</button>
              </td>
            </tr>
          `).join("");
        }
      } catch (e) {
        document.getElementById("stat-alerts-active").textContent = "N/A";
      }

      // 4. Fetch Investigations
      try {
        const invRes = await App.api.get("/api/v1/investigations?limit=10");
        const invItems = invRes.items || invRes || [];
        const activeInvs = invItems.filter((i) => i.status === "OPEN" || i.status === "IN_PROGRESS");
        document.getElementById("stat-investigations-active").textContent = activeInvs.length;
      } catch (e) {
        document.getElementById("stat-investigations-active").textContent = "N/A";
      }
    },
  },

  // ------------------------------------------------------------------------
  // 6. Camera Registry & Video Streams (Stage 6 & 7)
  // ------------------------------------------------------------------------
  cameras: {
    async load() {
      try {
        const cameras = await App.api.get("/api/v1/cameras");
        App.state.cameras = cameras;
        this.renderTable(cameras);
      } catch (e) {
        document.getElementById("cameras-table-tbody").innerHTML = `
          <tr><td colspan="7" style="text-align: center; color: var(--sev-critical);">Failed to load camera registry: ${e.message}</td></tr>
        `;
      }
    },

    renderTable(cameras) {
      const tbody = document.getElementById("cameras-table-tbody");
      if (!cameras || cameras.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-subtle);">Zero surveillance cameras registered.</td></tr>';
        return;
      }

      tbody.innerHTML = cameras.map((c) => {
        const isOnline = c.status === "ONLINE";
        const loc = c.location || {};
        const coords = (loc.latitude !== null && loc.latitude !== undefined && loc.longitude !== null && loc.longitude !== undefined)
          ? `${loc.latitude.toFixed(4)}, ${loc.longitude.toFixed(4)}`
          : '<span style="color: var(--status-demo); font-weight: 700;">UNMAPPED</span>';

        return `
          <tr>
            <td>
              <span class="badge-pill" style="${isOnline ? 'background: rgba(16, 185, 129, 0.2); color: var(--status-live);' : 'background: rgba(100, 116, 139, 0.2); color: var(--text-subtle);'} font-size: 10px;">
                ${c.status || "UNKNOWN"}
              </span>
            </td>
            <td>
              <strong style="color: #fff;">${c.name}</strong><br>
              <span style="font-family: var(--font-mono); font-size: 10px; color: var(--text-subtle);">${c.id}</span>
            </td>
            <td>${loc.name || loc.city || "Unassigned Location"}</td>
            <td style="font-family: var(--font-mono); font-size: 11px;">${coords}</td>
            <td><span class="badge-pill mode-demo" style="font-size: 9px;">${c.stream_type || "DEMO"}</span></td>
            <td style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">${c.resolution || "1080p"} / ${c.codec || "H.264"}</td>
            <td>
              <button class="btn-secondary" style="padding: 4px 10px; font-size: 11px;" onclick="App.cameras.openStream('${c.id}', '${c.name}', '${c.stream_type}', '${c.rtsp_url}')">📹 Monitor Stream</button>
            </td>
          </tr>
        `;
      }).join("");
    },

    filter() {
      const q = (document.getElementById("camera-search-input").value || "").toLowerCase();
      const statusFilter = document.getElementById("camera-status-filter").value;

      const filtered = App.state.cameras.filter((c) => {
        const matchName = (c.name || "").toLowerCase().includes(q) || (c.location?.city || "").toLowerCase().includes(q);
        const matchStatus = statusFilter === "ALL" || c.status === statusFilter;
        return matchName && matchStatus;
      });
      this.renderTable(filtered);
    },

    openStream(id, name, streamType, rtspUrl) {
      document.getElementById("stream-modal-cam-name").textContent = `${name} [ID: ${id.slice(0, 8)}]`;
      document.getElementById("stream-modal-badge").textContent = streamType || "DEMO";
      document.getElementById("stream-rtsp-text").textContent = rtspUrl || "rtsp://localhost:8554/live";
      document.getElementById("stream-status-message").textContent = `LIVE FEED TELEMETRY [${streamType}]`;
      App.ui.showModal("modal-stream-player");
    },
  },

  // ------------------------------------------------------------------------
  // 7. GIS Tactical Command Map (Stage 4 & 8)
  // ------------------------------------------------------------------------
  gis: {
    init() {
      if (App.state.map) return;

      const mapContainer = document.getElementById("gis-map-canvas");
      if (!mapContainer) return;

      // Initialize map with Gujarat center coordinates
      App.state.map = L.map("gis-map-canvas").setView([23.0225, 72.5714], 10);

      // Tile layer with offline error detection
      const tileLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "© OpenStreetMap contributors",
      });

      tileLayer.on("tileerror", () => {
        const banner = document.getElementById("tile-offline-alert");
        if (banner) banner.style.display = "block";
      });

      tileLayer.addTo(App.state.map);
    },

    async load() {
      this.init();
      setTimeout(() => {
        if (App.state.map) App.state.map.invalidateSize();
      }, 100);

      // Fetch GeoJSON FeatureCollection
      try {
        const geojson = await App.api.get("/api/v1/gis/cameras.geojson");
        this.plotCameras(geojson);
      } catch (e) {
        console.warn("GIS cameras.geojson fetch failed:", e);
      }

      // Fetch Unmapped Cameras
      try {
        const unmappedRes = await App.api.get("/api/v1/gis/unmapped");
        const count = unmappedRes.unmapped_count || 0;
        document.getElementById("gis-unmapped-count").textContent = count;
        
        const listDiv = document.getElementById("gis-unmapped-list");
        if (count === 0) {
          listDiv.innerHTML = '<div style="font-size: 11px; color: var(--status-live);">All registered surveillance cameras mapped.</div>';
        } else {
          listDiv.innerHTML = (unmappedRes.unmapped_cameras || []).map((u) => `
            <div style="background: var(--bg-primary); border: 1px solid var(--border-subtle); padding: 8px; border-radius: 4px; font-size: 11px;">
              <strong style="color: #fff;">${u.camera_name}</strong>
              <div style="color: var(--status-demo); margin-top: 2px;">${u.reason}</div>
            </div>
          `).join("");
        }
      } catch (e) {
        console.warn("GIS unmapped fetch failed:", e);
      }
    },

    plotCameras(geojson) {
      if (!App.state.map || !geojson || !geojson.features) return;

      // Clear existing markers
      Object.values(App.state.mapMarkers).forEach((m) => App.state.map.removeLayer(m));
      App.state.mapMarkers = {};

      const latlngs = [];
      geojson.features.forEach((feat) => {
        const coords = feat.geometry?.coordinates;
        if (!coords || coords.length < 2) return;
        const [lon, lat] = coords;
        latlngs.push([lat, lon]);

        const props = feat.properties || {};
        const isOnline = props.status === "ONLINE";

        // Create Leaflet circle marker
        const marker = L.circleMarker([lat, lon], {
          radius: 8,
          fillColor: isOnline ? "#10b981" : "#ef4444",
          color: "#ffffff",
          weight: 2,
          opacity: 1,
          fillOpacity: 0.9,
        }).addTo(App.state.map);

        marker.bindPopup(`
          <div style="font-family: sans-serif; font-size: 12px; color: #111;">
            <strong>${props.name || "Camera"}</strong><br>
            <span style="font-size: 10px; color: #666;">ID: ${props.camera_id}</span><br>
            Status: <strong>${props.status}</strong><br>
            Type: <strong>${props.stream_type}</strong>
          </div>
        `);

        App.state.mapMarkers[props.camera_id] = marker;
      });

      if (latlngs.length > 0) {
        App.state.map.fitBounds(L.latLngBounds(latlngs), { padding: [40, 40] });
      }
    },

    async searchNearby() {
      const lat = parseFloat(document.getElementById("gis-search-lat").value);
      const lon = parseFloat(document.getElementById("gis-search-lon").value);
      const rad = parseFloat(document.getElementById("gis-search-radius").value);

      if (isNaN(lat) || isNaN(lon) || isNaN(rad)) {
        App.ui.showToast("Invalid latitude, longitude, or radius values.", "error");
        return;
      }

      try {
        const results = await App.api.get(`/api/v1/gis/nearby-cameras?latitude=${lat}&longitude=${lon}&radius_km=${rad}`);
        App.ui.showToast(`Found ${results.length} cameras within ${rad} km`, "success");

        // Pan map to search center and draw circle
        if (App.state.map) {
          App.state.map.setView([lat, lon], 12);
          L.circle([lat, lon], {
            radius: rad * 1000,
            color: "#06b6d4",
            fillColor: "#06b6d4",
            fillOpacity: 0.15,
            weight: 1,
          }).addTo(App.state.map);
        }
      } catch (e) {
        App.ui.showToast(`Nearby search failed: ${e.message}`, "error");
      }
    },

    resetView() {
      if (App.state.map) {
        App.state.map.setView([23.0225, 72.5714], 10);
      }
    },
  },

  // ------------------------------------------------------------------------
  // 8. Vehicle Search & Cross-Camera Journey (Stages 11 & 12)
  // ------------------------------------------------------------------------
  vehicles: {
    async search() {
      const plate = (document.getElementById("vehicle-search-plate").value || "").trim().toUpperCase();
      if (!plate) {
        App.ui.showToast("Enter a valid vehicle license plate number.", "error");
        return;
      }

      try {
        const history = await App.api.get(`/api/v1/vehicles/${encodeURIComponent(plate)}/history`);
        App.state.currentPlateHistory = history;

        const resultsContainer = document.getElementById("vehicle-results-container");
        resultsContainer.style.display = "flex";

        // Summary metrics
        document.getElementById("veh-summary-plate").textContent = history.plate_number;
        document.getElementById("veh-summary-class").textContent = `Vehicle Type: ${history.vehicle_type || "Unknown"}`;
        document.getElementById("veh-summary-count").textContent = history.total_observations || 0;
        document.getElementById("veh-summary-first").textContent = App.ui.formatTime(history.first_seen);
        document.getElementById("veh-summary-last").textContent = App.ui.formatTime(history.last_seen);

        // Fetch Stage 12 Cross-Camera Correlation
        let correlation = null;
        try {
          correlation = await App.api.get(`/api/v1/vehicles/${encodeURIComponent(plate)}/correlation`);
        } catch (e) {
          console.log("No correlation available:", e);
        }

        this.renderJourneySequence(history, correlation);
        this.renderObservations(history.items || history.observations || []);
      } catch (e) {
        App.ui.showToast(`Vehicle search failed: ${e.message}`, "error");
        document.getElementById("vehicle-results-container").style.display = "none";
      }
    },

    renderJourneySequence(history, correlation) {
      const seqDiv = document.getElementById("veh-journey-sequence");
      const obs = history.items || history.observations || [];

      if (obs.length === 0) {
        seqDiv.innerHTML = '<div style="color: var(--text-subtle); font-size: 12px;">No observation sequence available for this plate.</div>';
        return;
      }

      let html = "";
      for (let i = 0; i < obs.length; i++) {
        const item = obs[i];
        const isFirst = i === 0;
        const isLast = i === obs.length - 1;

        html += `
          <div class="journey-node ${isFirst ? 'first' : ''} ${isLast && !isFirst ? 'last' : ''}">
            <div class="node-cam">${item.camera_name || `Camera #${i + 1}`}</div>
            <div style="font-size: 10px; color: var(--text-subtle);">${item.city || "Gujarat Sector"}</div>
            <div class="node-time">${App.ui.formatTime(item.timestamp || item.detected_at)}</div>
          </div>
        `;

        if (i < obs.length - 1) {
          const deltaMin = Math.max(1, Math.round((new Date(obs[i + 1].timestamp || obs[i + 1].detected_at) - new Date(item.timestamp || item.detected_at)) / 60000));
          html += `
            <div class="journey-arrow">
              ➔
              <span>+${deltaMin}m</span>
            </div>
          `;
        }
      }
      seqDiv.innerHTML = html;
    },

    renderObservations(observations) {
      const tbody = document.getElementById("veh-observations-tbody");
      if (observations.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-subtle);">No detections recorded.</td></tr>';
        return;
      }

      tbody.innerHTML = observations.map((o) => `
        <tr>
          <td style="font-family: var(--font-mono); font-size: 11px;">${App.ui.formatTime(o.timestamp || o.detected_at)}</td>
          <td><strong>${o.camera_name || o.camera_id}</strong></td>
          <td>${o.location_name || o.city || "Gujarat Highway Sector"}</td>
          <td>${Math.round((o.confidence_vehicle || 0.95) * 100)}% / ${Math.round((o.confidence_plate || 0.92) * 100)}%</td>
          <td><span class="badge-pill mode-demo" style="font-size: 9px;">${o.detection_source || "DEMO"}</span></td>
        </tr>
      `).join("");
    },

    async previewRouteOnGIS() {
      const hist = App.state.currentPlateHistory;
      const obs = hist?.items || hist?.observations || [];
      if (!hist || obs.length === 0) {
        App.ui.showToast("No route observations to plot.", "error");
        return;
      }

      // Collect waypoints
      const waypoints = obs
        .filter((o) => o.latitude !== null && o.longitude !== null && o.latitude !== undefined && o.longitude !== undefined)
        .map((o, idx) => ({
          latitude: o.latitude,
          longitude: o.longitude,
          sequence: idx + 1,
        }));

      if (waypoints.length === 0) {
        App.ui.showToast("All observation cameras are UNMAPPED. Cannot plot route geometry.", "error");
        return;
      }

      try {
        const routeGeoJSON = await App.api.post("/api/v1/gis/route-preview", { waypoints });
        App.nav.switchView("gis");
        setTimeout(() => {
          if (App.state.map && routeGeoJSON.geometry?.coordinates) {
            const latlngs = routeGeoJSON.geometry.coordinates.map(([lon, lat]) => [lat, lon]);
            if (App.state.routePolyline) {
              App.state.map.removeLayer(App.state.routePolyline);
            }
            App.state.routePolyline = L.polyline(latlngs, { color: "#06b6d4", weight: 4, dashArray: "6, 8" }).addTo(App.state.map);
            App.state.map.fitBounds(App.state.routePolyline.getBounds(), { padding: [50, 50] });
            App.ui.showToast("Correlated trajectory plotted on GIS tactical map.", "success");
          }
        }, 300);
      } catch (e) {
        App.ui.showToast(`Route preview error: ${e.message}`, "error");
      }
    },
  },

  // ------------------------------------------------------------------------
  // 9. Live Detections & ANPR Stream (Stages 6 & 7)
  // ------------------------------------------------------------------------
  detections: {
    async load() {
      try {
        const res = await App.api.get("/api/v1/detections?limit=50");
        const items = res.items || res || [];
        App.state.detections = items;
        this.renderTable(items);
      } catch (e) {
        document.getElementById("detections-stream-tbody").innerHTML = `
          <tr><td colspan="7" style="text-align: center; color: var(--sev-critical);">Failed to load detections: ${e.message}</td></tr>
        `;
      }
    },

    renderTable(items) {
      const tbody = document.getElementById("detections-stream-tbody");
      if (!items || items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-subtle);">No vehicle detections recorded.</td></tr>';
        return;
      }

      tbody.innerHTML = items.map((d) => `
        <tr>
          <td style="font-family: var(--font-mono); font-size: 11px;">${App.ui.formatTime(d.detected_at)}</td>
          <td><span class="plate-badge">${d.plate_number || "NO PLATE"}</span></td>
          <td style="text-transform: capitalize;">${d.vehicle_type || "Car"}</td>
          <td>${Math.round((d.confidence_vehicle || 0.95) * 100)}%</td>
          <td>${Math.round((d.confidence_plate || 0.92) * 100)}%</td>
          <td>${d.camera_name || d.camera_id?.slice(0, 8) || "Sector Cam"}</td>
          <td><span class="badge-pill mode-demo" style="font-size: 9px;">${d.is_demo ? "DEMO" : "LIVE"}</span></td>
        </tr>
      `).join("");
    },

    prependLive(d) {
      const tbody = document.getElementById("detections-stream-tbody");
      if (!tbody) return;
      const row = document.createElement("tr");
      row.style.background = "rgba(6, 182, 212, 0.1)";
      row.innerHTML = `
        <td style="font-family: var(--font-mono); font-size: 11px;">${App.ui.formatTime(d.detected_at || new Date().toISOString())}</td>
        <td><span class="plate-badge" style="border-color: var(--cyan-primary);">${d.plate_number || "NO PLATE"}</span></td>
        <td style="text-transform: capitalize;">${d.vehicle_type || "Car"}</td>
        <td>${Math.round((d.confidence_vehicle || 0.95) * 100)}%</td>
        <td>${Math.round((d.confidence_plate || 0.92) * 100)}%</td>
        <td>${d.camera_name || "Live Node"}</td>
        <td><span class="badge-pill mode-demo" style="font-size: 9px;">LIVE-WS</span></td>
      `;
      tbody.insertBefore(row, tbody.firstChild);
    },

    refresh() {
      this.load();
    },
  },

  // ------------------------------------------------------------------------
  // 10. Watchlist Management (Stage 9)
  // ------------------------------------------------------------------------
  watchlists: {
    async load() {
      try {
        const watchlists = await App.api.get("/api/v1/watchlists");
        App.state.watchlists = watchlists;
        this.renderTable(watchlists);

        // Populate modal select
        const sel = document.getElementById("entry-create-watchlist-id");
        if (sel) {
          sel.innerHTML = '<option value="">Select Watchlist...</option>' + watchlists.map((w) => `
            <option value="${w.id}">${w.name} (${w.category})</option>
          `).join("");
        }
      } catch (e) {
        document.getElementById("watchlists-table-tbody").innerHTML = `
          <tr><td colspan="6" style="text-align: center; color: var(--sev-critical);">Failed to load watchlists: ${e.message}</td></tr>
        `;
      }
    },

    renderTable(watchlists) {
      const tbody = document.getElementById("watchlists-table-tbody");
      if (!watchlists || watchlists.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-subtle);">Zero active hotlists configured.</td></tr>';
        return;
      }

      tbody.innerHTML = watchlists.map((w) => `
        <tr>
          <td><strong style="color: #fff;">${w.name}</strong></td>
          <td><span class="badge-pill" style="background: rgba(59, 130, 246, 0.2); color: var(--blue-primary); font-size: 9px;">${w.category}</span></td>
          <td><span class="badge-pill" style="background: rgba(239, 68, 68, 0.2); color: var(--sev-critical); font-size: 9px;">${w.severity}</span></td>
          <td><span style="color: var(--status-live); font-weight: 700;">${w.is_active ? "ACTIVE" : "INACTIVE"}</span></td>
          <td>${w.entry_count !== undefined ? w.entry_count : (w.entries?.length || 1)} targets</td>
          <td>
            <button class="btn-secondary" style="padding: 2px 8px; font-size: 11px;" onclick="App.watchlists.viewEntries('${w.id}')">Inspect Entries</button>
          </td>
        </tr>
      `).join("");
    },

    async viewEntries(watchlistId) {
      try {
        const entries = await App.api.get(`/api/v1/watchlists/${watchlistId}/entries`);
        const plates = entries.map((e) => e.plate_number).join(", ");
        App.ui.showToast(`Enrolled Targets: ${plates || "None"}`, "info");
      } catch (e) {
        App.ui.showToast(`Failed to load entries: ${e.message}`, "error");
      }
    },

    async submitAddEntry() {
      const wId = document.getElementById("entry-create-watchlist-id").value;
      const plate = document.getElementById("entry-create-plate").value.trim().toUpperCase();
      const fir = document.getElementById("entry-create-fir").value.trim();
      const model = document.getElementById("entry-create-model").value.trim();

      if (!wId || !plate) {
        App.ui.showToast("Select target watchlist and provide license plate.", "error");
        return;
      }

      try {
        await App.api.post(`/api/v1/watchlists/${wId}/entries`, {
          plate_number: plate,
          fir_number: fir || undefined,
          vehicle_make_model: model || undefined,
          notes: "Enrolled via Sentinel Command Center UI",
        });

        App.ui.showToast(`Plate ${plate} enrolled into hotlist successfully.`, "success");
        App.ui.hideModal("modal-add-entry");
        this.load();
      } catch (e) {
        App.ui.showToast(`Enrollment error: ${e.message}`, "error");
      }
    },
  },

  // ------------------------------------------------------------------------
  // 11. Alert Center (Stage 10)
  // ------------------------------------------------------------------------
  alerts: {
    async load() {
      try {
        const alerts = await App.api.get("/api/v1/alerts?limit=50");
        const items = alerts.items || alerts || [];
        App.state.alerts = items;
        this.renderTable(items);

        const unreadCount = items.filter((a) => a.status === "NEW").length;
        const badge = document.getElementById("sidebar-alert-counter");
        if (unreadCount > 0) {
          badge.textContent = unreadCount;
          badge.style.display = "inline-block";
        } else {
          badge.style.display = "none";
        }
      } catch (e) {
        document.getElementById("alerts-table-tbody").innerHTML = `
          <tr><td colspan="6" style="text-align: center; color: var(--sev-critical);">Failed to load alerts: ${e.message}</td></tr>
        `;
      }
    },

    renderTable(alerts) {
      const tbody = document.getElementById("alerts-table-tbody");
      if (!alerts || alerts.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-subtle);">Zero incident alerts recorded.</td></tr>';
        return;
      }

      tbody.innerHTML = alerts.map((a) => `
        <tr>
          <td><span class="badge-pill" style="background: rgba(239, 68, 68, 0.2); color: var(--sev-critical); font-size: 10px;">${a.severity}</span></td>
          <td><span class="plate-badge" style="border-color: var(--sev-critical);">${a.plate_number}</span></td>
          <td>
            <span class="badge-pill" style="${a.status === 'NEW' ? 'background: #7f1d1d; color: #fca5a5;' : 'background: #14532d; color: #86efac;'} font-size: 9px;">
              ${a.status}
            </span>
          </td>
          <td>${a.camera_id ? a.camera_id.slice(0, 8) : "Edge Camera"}</td>
          <td style="font-family: var(--font-mono); font-size: 11px;">${App.ui.formatTime(a.created_at)}</td>
          <td>
            ${a.status === 'NEW' ? `<button class="btn-primary" style="padding: 2px 8px; font-size: 10px;" onclick="App.alerts.acknowledge('${a.id}')">Acknowledge</button>` : ''}
            ${a.status !== 'RESOLVED' ? `<button class="btn-secondary" style="padding: 2px 8px; font-size: 10px; margin-left: 4px;" onclick="App.alerts.resolve('${a.id}')">Resolve</button>` : '<span style="color: var(--status-live); font-size: 11px;">✓ Resolved</span>'}
          </td>
        </tr>
      `).join("");
    },

    async acknowledge(id) {
      try {
        await App.api.patch(`/api/v1/alerts/${id}/status`, { status: "ACKNOWLEDGED" });
        App.ui.showToast("Alert acknowledged by officer.", "success");
        this.load();
      } catch (e) {
        App.ui.showToast(`Failed to acknowledge alert: ${e.message}`, "error");
      }
    },

    async resolve(id) {
      try {
        await App.api.patch(`/api/v1/alerts/${id}/status`, { status: "RESOLVED", resolution_notes: "Resolved by command operator." });
        App.ui.showToast("Alert marked resolved.", "success");
        this.load();
      } catch (e) {
        App.ui.showToast(`Failed to resolve alert: ${e.message}`, "error");
      }
    },

    filter() {
      const sev = document.getElementById("alert-severity-filter").value;
      const stat = document.getElementById("alert-status-filter").value;
      const filtered = App.state.alerts.filter((a) => {
        const matchSev = sev === "ALL" || a.severity === sev;
        const matchStat = stat === "ALL" || a.status === stat;
        return matchSev && matchStat;
      });
      this.renderTable(filtered);
    },

    incrementBadge() {
      const badge = document.getElementById("sidebar-alert-counter");
      const current = parseInt(badge.textContent || "0", 10) + 1;
      badge.textContent = current;
      badge.style.display = "inline-block";
    },

    prependLive(a) {
      const tbody = document.getElementById("alerts-table-tbody");
      if (!tbody) return;
      const row = document.createElement("tr");
      row.style.background = "rgba(239, 68, 68, 0.15)";
      row.innerHTML = `
        <td><span class="badge-pill" style="background: rgba(239, 68, 68, 0.3); color: var(--sev-critical); font-size: 10px;">${a.severity || "CRITICAL"}</span></td>
        <td><span class="plate-badge" style="border-color: var(--sev-critical);">${a.plate_number}</span></td>
        <td><span class="badge-pill" style="background: #7f1d1d; color: #fca5a5; font-size: 9px;">NEW</span></td>
        <td>${a.camera_id ? a.camera_id.slice(0, 8) : "Realtime Node"}</td>
        <td style="font-family: var(--font-mono); font-size: 11px;">${App.ui.formatTime(new Date().toISOString())}</td>
        <td><button class="btn-primary" style="padding: 2px 8px; font-size: 10px;" onclick="App.alerts.acknowledge('${a.id}')">Acknowledge</button></td>
      `;
      tbody.insertBefore(row, tbody.firstChild);
    },
  },

  // ------------------------------------------------------------------------
  // 12. Investigation Workspace (Stage 13)
  // ------------------------------------------------------------------------
  investigations: {
    async load() {
      try {
        const res = await App.api.get("/api/v1/investigations?limit=50");
        const items = res.items || res || [];
        App.state.investigations = items;
        this.renderTable(items);
      } catch (e) {
        document.getElementById("investigations-table-tbody").innerHTML = `
          <tr><td colspan="7" style="text-align: center; color: var(--sev-critical);">Failed to load investigations: ${e.message}</td></tr>
        `;
      }
    },

    renderTable(items) {
      const tbody = document.getElementById("investigations-table-tbody");
      if (!items || items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-subtle);">Zero active case investigations.</td></tr>';
        return;
      }

      tbody.innerHTML = items.map((inv) => `
        <tr>
          <td><strong style="color: var(--cyan-primary); font-family: var(--font-mono);">${inv.case_number}</strong></td>
          <td><strong style="color: #fff;">${inv.title}</strong></td>
          <td>${inv.target_plate ? `<span class="plate-badge">${inv.target_plate}</span>` : '<span style="color: var(--text-subtle);">None</span>'}</td>
          <td><span class="badge-pill mode-demo" style="font-size: 9px;">${inv.status}</span></td>
          <td>${inv.lead_detective_name || inv.lead_detective_id?.slice(0, 8) || "Detective"}</td>
          <td style="font-family: var(--font-mono); font-size: 11px;">${App.ui.formatTime(inv.created_at)}</td>
          <td>
            <button class="btn-secondary" style="padding: 2px 8px; font-size: 11px;" onclick="App.investigations.inspectCase('${inv.id}')">Open Case File</button>
          </td>
        </tr>
      `).join("");
    },

    async inspectCase(invId) {
      try {
        const events = await App.api.get(`/api/v1/investigations/${invId}/events`);
        App.ui.showToast(`Case File has ${events.length} attached observation events.`, "info");
      } catch (e) {
        App.ui.showToast(`Error opening case: ${e.message}`, "error");
      }
    },

    async submitCreate() {
      const caseNum = document.getElementById("inv-create-case-number").value.trim();
      const title = document.getElementById("inv-create-title").value.trim();
      const plate = document.getElementById("inv-create-plate").value.trim().toUpperCase() || undefined;
      const desc = document.getElementById("inv-create-desc").value.trim() || undefined;

      if (!caseNum || !title) {
        App.ui.showToast("Case number and title are required.", "error");
        return;
      }

      try {
        await App.api.post("/api/v1/investigations", {
          case_number: caseNum,
          title: title,
          target_plate: plate,
          description: desc,
        });

        App.ui.showToast(`Investigation case ${caseNum} opened successfully.`, "success");
        App.ui.hideModal("modal-new-investigation");
        this.load();
      } catch (e) {
        App.ui.showToast(`Case creation error: ${e.message}`, "error");
      }
    },
  },

  // ------------------------------------------------------------------------
  // 13. Audit Trail (SuperAdmin / Auditor)
  // ------------------------------------------------------------------------
  audit: {
    async load() {
      try {
        const res = await App.api.get("/api/v1/audit-logs?limit=50");
        const items = res.items || res || [];
        this.renderTable(items);
      } catch (e) {
        document.getElementById("audit-table-tbody").innerHTML = `
          <tr><td colspan="6" style="text-align: center; color: var(--sev-critical);">Failed to load audit logs: ${e.message}</td></tr>
        `;
      }
    },

    renderTable(items) {
      const tbody = document.getElementById("audit-table-tbody");
      if (!items || items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-subtle);">Audit log empty.</td></tr>';
        return;
      }

      tbody.innerHTML = items.map((l) => `
        <tr>
          <td style="font-family: var(--font-mono); font-size: 11px;">${App.ui.formatTime(l.created_at)}</td>
          <td><strong style="color: var(--cyan-primary); font-family: var(--font-mono);">${l.badge_number || "SYSTEM"}</strong></td>
          <td><span class="badge-pill" style="background: rgba(30, 41, 59, 0.5); color: #fff; font-size: 10px;">${l.action}</span></td>
          <td>${l.resource_type || "SYSTEM"}</td>
          <td style="font-family: var(--font-mono); font-size: 11px;">${l.ip_address || "127.0.0.1"}</td>
          <td style="font-size: 11px; color: var(--text-muted);">${l.payload_summary || "--"}</td>
        </tr>
      `).join("");
    },

    refresh() {
      this.load();
    },
  },

  // ------------------------------------------------------------------------
  // 14. Personnel Management (SuperAdmin Only)
  // ------------------------------------------------------------------------
  users: {
    async load() {
      try {
        const res = await App.api.get("/api/v1/users/");
        const items = res.items || res || [];
        this.renderTable(items);
      } catch (e) {
        document.getElementById("users-table-tbody").innerHTML = `
          <tr><td colspan="6" style="text-align: center; color: var(--sev-critical);">Failed to load personnel accounts: ${e.message}</td></tr>
        `;
      }
    },

    renderTable(items) {
      const tbody = document.getElementById("users-table-tbody");
      if (!items || items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-subtle);">Zero user accounts found.</td></tr>';
        return;
      }

      tbody.innerHTML = items.map((u) => `
        <tr>
          <td><strong style="color: var(--cyan-primary); font-family: var(--font-mono);">${u.badge_number}</strong></td>
          <td><strong style="color: #fff;">${u.full_name}</strong></td>
          <td>${u.email}</td>
          <td><span class="user-role-chip role-${(u.role_name || u.role || '').toLowerCase()}">${u.role_name || u.role || "Operator"}</span></td>
          <td>${u.department_name || u.department_code || "State HQ"}</td>
          <td><span style="color: var(--status-live); font-weight: 700;">${u.is_active ? "ACTIVE" : "DEACTIVATED"}</span></td>
        </tr>
      `).join("");
    },
  },

  // ------------------------------------------------------------------------
  // 15. UI Helpers, Modals & Toasts
  // ------------------------------------------------------------------------
  ui: {
    updateAuthUI() {
      const user = App.state.user;
      const userBadge = document.getElementById("user-badge-container");
      const loginBtn = document.getElementById("btn-login-open");
      const adminNavTitle = document.getElementById("admin-nav-title");
      const adminNavMenu = document.getElementById("admin-nav-menu");
      const navAudit = document.getElementById("nav-audit");
      const navUsers = document.getElementById("nav-users");

      if (user) {
        userBadge.style.display = "flex";
        loginBtn.style.display = "none";
        document.getElementById("user-display-name").textContent = user.full_name;
        document.getElementById("user-badge-id").textContent = user.badge_number;
        const roleChip = document.getElementById("user-role-chip");
        roleChip.textContent = user.role;
        roleChip.className = `user-role-chip role-${user.role.toLowerCase()}`;

        // Governance menu clearance checks
        const isSuperAdmin = user.role === "SuperAdmin";
        const isAuditor = user.role === "Auditor";
        if (isSuperAdmin || isAuditor) {
          adminNavTitle.style.display = "block";
          adminNavMenu.style.display = "flex";
          navAudit.style.display = "block";
          navUsers.style.display = isSuperAdmin ? "block" : "none";
        } else {
          adminNavTitle.style.display = "none";
          adminNavMenu.style.display = "none";
        }
      } else {
        userBadge.style.display = "none";
        loginBtn.style.display = "inline-block";
        adminNavTitle.style.display = "none";
        adminNavMenu.style.display = "none";
      }
    },

    showModal(modalId) {
      const m = document.getElementById(modalId);
      if (m) m.classList.add("active");
    },

    hideModal(modalId) {
      const m = document.getElementById(modalId);
      if (m) m.classList.remove("active");
    },

    showLoginModal() {
      this.showModal("modal-login");
    },

    showNewInvestigationModal() {
      if (!App.auth.hasPermission("investigations:write")) {
        this.showToast("Permission denied: Requires Investigator or SuperAdmin clearance.", "error");
        return;
      }
      this.showModal("modal-new-investigation");
    },

    showAddEntryModal() {
      if (!App.auth.hasPermission("watchlists:write")) {
        this.showToast("Permission denied: Requires watchlists:write clearance.", "error");
        return;
      }
      this.showModal("modal-add-entry");
    },

    showEnrollUserModal() {
      if (!App.auth.hasPermission("users:manage")) {
        this.showToast("Permission denied: Requires SuperAdmin clearance.", "error");
        return;
      }
      this.showToast("Enrollment API available in SuperAdmin CLI & REST.", "info");
    },

    showToast(message, type = "info") {
      const container = document.getElementById("toast-container");
      if (!container) return;

      const toast = document.createElement("div");
      toast.className = `toast toast-${type}`;
      toast.innerHTML = `
        <span style="font-size: 16px;">${type === "critical" ? "🚨" : type === "success" ? "✓" : "ℹ️"}</span>
        <span>${message}</span>
      `;
      container.appendChild(toast);

      setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 300);
      }, 4000);
    },

    formatTime(isoString) {
      if (!isoString) return "--";
      try {
        const d = new Date(isoString);
        return d.toLocaleTimeString() + " " + d.toLocaleDateString();
      } catch (e) {
        return isoString;
      }
    },
  },
};

// Auto boot on DOM Content Loaded
document.addEventListener("DOMContentLoaded", () => {
  App.auth.init().then(() => {
    App.dashboard.refresh();
  });
});
