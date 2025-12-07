package main

// For /expandStatus polling
var searchTicker = struct {
	Artist string `json:"artist"`
	Count  int    `json:"count"`
	Max    int    `json:"max"`
	Depth  int    `json:"depth"`
}{}
