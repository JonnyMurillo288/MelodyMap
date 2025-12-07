package main

import (
	sixdegrees "github.com/Jonnymurillo288/MelodyMap/sixDegrees"
)

// Returned by MusicBrainzNeighborProvider()
// Used only inside RunSearchOptsBFS
type NeighborEdge struct {
	Artist *sixdegrees.Artists
	Track  []sixdegrees.Track
	Link   string // optional: MB recording URI
}
