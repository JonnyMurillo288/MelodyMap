FROM golang:1.24.0 AS build

WORKDIR /app

# Dependencies first (cache-friendly)
COPY go.mod go.sum ./
RUN go mod download

# Copy source and build
COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o server ./main

# ---------- Runtime stage ----------
FROM gcr.io/distroless/base-debian12

WORKDIR /app
COPY --from=build /app/server /app/server

EXPOSE 8080
CMD ["/app/server"]