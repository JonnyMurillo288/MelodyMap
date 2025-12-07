package search

import (
	sixdegrees "github.com/Jonnymurillo288/SixDegreesSpotify/sixDegrees"
)

// Returned to the frontend:
type NeighborEntry struct {
	Name      string         `json:"Name"`
	Neighbors []NeighborEdge `json:"Neighbors"`
}

// LookupNeighbors resolves an artist by name, gets neighbors from DB/MusicBrainz.
func LookupNeighbors(name string) (*NeighborEntry, error) {
	if name == "" {
		return &NeighborEntry{Name: name, Neighbors: []NeighborEdge{}}, nil
	}

	mb := NewMBClient()

	hits, err := mb.SearchArtist(name)
	if err != nil || len(hits) == 0 {
		return &NeighborEntry{Name: name, Neighbors: []NeighborEdge{}}, nil
	}

	artist := &sixdegrees.Artists{
		ID:   hits[0].ID,
		Name: hits[0].Name,
	}

	// open DB store
	store, err := Open("")
	if err != nil {
		return nil, err
	}

	neighbors, _, err := store.MusicBrainzNeighborProvider(artist, 5000, false)
	if err != nil {
		return &NeighborEntry{Name: artist.Name, Neighbors: []NeighborEdge{}}, nil
	}

	// Flatten edges to NeighborEntry form
	out := []NeighborEdge{}
	for _, nb := range neighbors {
		if nb == nil || nb.Artist == nil {
			continue
		}
		out = append(out, *nb)
	}

	return &NeighborEntry{
		Name:      artist.Name,
		Neighbors: out,
	}, nil
}
