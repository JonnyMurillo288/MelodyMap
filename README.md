
# SixDegreesSpotify – How the Site Works
### [Link to Site](https://melody-map.com/)

![use image](https://github.com/JonnyMurillo288/MelodyMap/blob/main/ezgif-140c2ab38565cd93.gif)

SixDegreesSpotify (Melody‑Map) is an interactive web application that reveals how any two musical artists are connected across the global collaboration graph.  
Instead of relying on simple metadata, the site builds a structured network of artists, recordings, and shared collaborations—then traces the shortest path between two artists in real time.

---

## Overview

When you enter a **start artist** and a **target artist**, the site performs three high‑level steps:

### 1. Artist Identification
The system searches its indexed MusicBrainz/Spotify–linked database to:
- Normalize artist names  
- Handle ambiguous or duplicate matches  
- Retrieve canonical artist IDs used for graph traversal  

This ensures that the search runs on verified entities, not fuzzy text matches.

---

### 2. Collaboration Graph Expansion
Once both artists are identified, the backend begins expanding outward from the start artist using a **Breadth‑First Search (BFS)** across collaboration data.

Each “neighbor” relationship is formed through:
- Shared recordings  
- Featured appearances  
- Joint albums or EPs  
- Remix credits  
- Any track‑level collaboration stored in the dataset  

The BFS continues across layers until the target artist is reached or all reachable connections are exhausted.

A live ticker on the site shows:
- Current depth  
- Artist currently being expanded  
- Number of neighbors scanned  

This provides transparency into the real‑time search complexity.

---

### 3. Path Reconstruction & Visualization
When a link is found, the system backtracks through the BFS tree to reconstruct the shortest path.

Each hop includes:
- `From` and `To` artist  
- All tracks that connect them  
- Track previews or album art when available  

The front‑end renders the path visually and displays hover panels listing collaboration details.

You may optionally:
- **Generate a Spotify playlist** containing all songs used in the discovered path  
- Click into each track’s Spotify link  
- View the artist/track cards with imagery and metadata  

---

## What the App Does *Not* Require
This site is **not** a tool you must install or run locally.  
There is:
- No local OAuth setup  
- No CLI required  
- No need for API keys  

All authentication, data processing, and graph search logic happens on the hosted backend.

---

## Key Features
- Fast, database‑driven artist lookup  
- Real‑time BFS expansion across millions of collaboration edges  
- Full track‑level connection metadata  
- Visual, interactive UI  
- Optional playlist creation via your Spotify account  
- Accurate handling of features, remixes, joint albums, and multi‑artist credits  

---

## Additional Notes
- All track/artist images and previews originate from the Spotify Web API.  
- Collaboration edges originate from MusicBrainz → Spotify linkage.  
- The app handles rate‑limited APIs, caching, DB indexing, and batching internally.  

---

