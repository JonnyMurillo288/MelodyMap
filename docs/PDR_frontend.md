# Preliminary Design Review (PDR): SixDegreeSpotify Frontend

**Project:** SixDegreeSpotify  
**Subsystem:** Front-End Web Application  
**Date:** _(insert date)_  
**Author:** Jonathan Murillo  

---

## 1. Overview

The SixDegreeSpotify frontend provides a minimal web-based interface for exploring collaboration paths between musical artists using Spotify data.  
It communicates directly with a Go backend that handles OAuth authentication, caching, and graph traversal (BFS/Dijkstra variants).  

The frontend is implemented in **HTML + JavaScript**, served by the Go backend itself. Users can input two artists, trigger a search, and view the resulting collaboration path in real time.  

Future versions will extend this interface with graph visualizations and richer analytics.

---

## 2. Objectives and Scope

**Primary Objectives**
- Provide a browser interface to input two artist names and trigger a backend search.  
- Display artist-to-artist collaboration paths based on Spotify track data.  
- Integrate with Spotify OAuth handled by the backend.  
- Maintain a modular design for future visualization and styling expansion.

**Out of Scope (for now)**
- Persistent user sessions or saved search history.  
- Advanced styling or branding.  
- Graph visualization (planned future feature).

---

## 3. System Context

```
+-------------------+          +---------------------------+          +----------------+
|   User (Browser)  |  <--->   |  Frontend (HTML/JS App)  |  <--->   |   Go Backend   |
|                   |          | - UI + fetch("/search")  |          | - Web Server   |
| - Inputs artists  |          | - Displays results       |          | - BFS Logic    |
| - Views paths     |          |                         |          | - Spotify API  |
+-------------------+          +---------------------------+          +----------------+
```

The Go backend serves the static frontend files and exposes API routes.  
When the frontend sends a request, the backend runs the internal BFS logic directly — **no shell execution or external process**.  
Results are returned to the frontend as JSON and rendered dynamically.

---

## 4. User Flow

1. **Home Page / Search View**
   - User enters a **start artist** and **target artist**.  
   - User clicks **Search**, which triggers a JS `fetch("/search")` call.  
   - Backend receives the request and runs the BFS search.

2. **Processing / Loading**
   - The frontend displays a spinner or “Searching…” indicator until results arrive.

3. **Results View**
   - JSON response is formatted and displayed:
     ```
     1. Lil Wayne —[Last Of A Dying Breed]→ Ludacris
     2. Ludacris —[Last Of A Dying Breed]→ Pitbull
     ```
   - The results will be saved at results/results.json
   - Optional metadata: elapsed time, path depth, popularity weights.

4. **Error Handling**
   - Descriptive messages shown for missing artists, search depth limits, or API errors.

---

## 5. Front-End Architecture

**Languages & Frameworks**
- HTML / CSS / Vanilla JavaScript  
- Backend: Go (`net/http`, custom SixDegreeSpotify search logic)

**Data Flow**
```
Browser JS (fetch /search)
        ↓
Go Backend HTTP Handler
        ↓
Internal BFS/Dijkstra Search
        ↓
JSON Response
        ↓
Browser renders results dynamically
```

**Example Endpoints**
- `POST /search` → accepts `{start, target}` JSON, returns collaboration path  
- `GET /auth` → initiates Spotify OAuth  
- `GET /callback` → handles OAuth redirect  
- `GET /status` → optional backend health check  

---

## 6. UI Components

| Component | Description | Status |
|------------|--------------|---------|
| **Header / Title Bar** | “SixDegreeSpotify” logo/text | Implemented |
| **Search Input Fields** | Two text boxes: `Start Artist`, `Target Artist` | Implemented |
| **Search Button** | Submits query to backend via `fetch` | Implemented |
| **Loading Indicator** | Simple text or spinner | Implemented |
| **Results Container** | Displays formatted path list | Implemented |
| **Error Banner** | Displays error messages | Planned |
| **Graph Container** | Placeholder for D3.js/Cytoscape.js graph | Planned |

---

## 7. Authentication (OAuth)

Spotify OAuth is managed entirely by the Go backend.  
Frontend responsibilities:
- Provide a **“Login with Spotify”** button linking to `/auth`.  
- Receive redirect after successful authentication.  
- Once authorized, allow user to perform searches.  

No tokens or secrets are stored client-side.

---

## 8. Planned Future Enhancements

| Feature | Description |
|----------|-------------|
| Graph Visualization | Visualize artist connection graphs using D3.js or Cytoscape.js. |
| Popularity Weight Controls | UI slider to balance path length vs. popularity weighting. |
| Search History | Allow users to view and rerun recent searches. |
| Styling / Theming | Add Tailwind CSS and responsive layout. |
| Export Options | Enable exporting search results to CSV or image. |

---

## 9. Risks and Considerations

| Risk | Impact | Mitigation |
|------|---------|------------|
| CORS or request header issues | API calls blocked | Configure proper CORS in Go backend |
| Spotify API rate limits | Throttled or failed requests | Use backend caching and exponential backoff |
| Token expiration | Failed authentication | Add token refresh mechanism |
| Large JSON responses | Slow rendering | Paginate or collapse long paths |

---

## 10. Next Steps

1. Finalize `/search`, `/auth`, and `/callback` handlers in Go.  
2. Connect frontend `fetch()` to backend endpoints.  
3. Implement frontend success/error handling logic.  
4. Add basic responsive styling.  
5. Begin prototype for graph visualization module.  

---

## Appendix A: Example File Structure (Proposed)

```
sixdegrees-frontend/
├── index.html
├── script.js
├── style.css
├── /assets
│   ├── logo.png
│   └── spinner.gif
└── /public
    └── oauth_redirect.html
```

---

## Appendix B: Example Fetch Call

```javascript
async function runSearch() {
  const start = document.getElementById("startArtist").value;
  const target = document.getElementById("targetArtist").value;
  const resultsDiv = document.getElementById("results");
  
  resultsDiv.innerHTML = "Searching...";
  const response = await fetch("/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ start, target }),
  });

  if (!response.ok) {
    resultsDiv.innerHTML = "Error: " + response.statusText;
    return;
  }

  const data = await response.json();
  resultsDiv.innerHTML = data.path
    .map((step, i) => `${i + 1}. ${step}`)
    .join("<br>");
}
```
