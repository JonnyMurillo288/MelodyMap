package main

import (
	"flag"
	"fmt"

	machinelearning "github.com/Jonnymurillo288/MelodyMap/internal/machinelearning"
)

func main() {
	// Define CLI flags
	i := flag.Int("i", 0, "What index to start on for artists search ")
	numArtists := flag.Int("n", 1000, "Number of artists to process (N)")
	workers := flag.Int("workers", 10, "Number of concurrent workers")

	flag.Parse()

	// Validate flags
	if *numArtists <= 0 {
		fmt.Println("Error: -n must be greater than 0")
		flag.Usage()
		return
	}
	if *workers <= 0 {
		fmt.Println("Error: -workers must be greater than 0")
		flag.Usage()
		return
	}

	fmt.Printf("Starting batch processing with N=%d, workers=%d\n", *numArtists, *workers)
	machinelearning.RunBatch(*i, *numArtists, *workers)
}
