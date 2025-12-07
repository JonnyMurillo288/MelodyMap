# SixDegreesSpotify

SixDegreesSpotify discovers relationships between two musical artists using Spotify data, inspired by the "six degrees" concept. Given a start artist and a target artist, it builds a collaboration graph and finds a path via BFS (unweighted) or a weighted search.

---

## Prerequisites
- Go 1.21+ (recommended)
- Spotify Developer account and app
- Network access to Spotify Web API

---

## Authentication Setup
The app uses Spotify OAuth to obtain an access token, stored locally. Do not commit secrets or tokens.

1) Create a Spotify application
- Redirect URL: `http://localhost:8392/auth`

2) Create auth config file
```bash
cp main/authConfig.sample.json main/authConfig.txt
# Edit main/authConfig.txt and fill in client_id and client_secret
```

3) Run the auth server and complete login
```bash
go run ./main/auth.go
# Open http://localhost:8392 in your browser and approve access
# The token will be written to main/authToken.txt
```

---

## CLI Usage
Run an unweighted shortest path search:
```bash
go run main.go -start "Artist A" -find "Artist B"
```

If required flags are missing, the program prints usage and exits with code 1.

Optional flags (planned):
- `-depth` (limit BFS depth)
- `-weighted` (use weighted search)
- `-verbose` (more detailed logs)

---

## Notes
- Secrets (`main/authConfig.txt`, `main/authToken.txt`) are ignored via .gitignore.
- API rate limiting and pagination enhancements are planned; current behavior may be limited.

---

## License
MIT (or project default).