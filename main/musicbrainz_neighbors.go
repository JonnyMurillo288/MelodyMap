package main

import (
	"github.com/Jonnymurillo288/SixDegreesSpotify/musicbrainz"

	sixdegrees "github.com/Jonnymurillo288/SixDegreesSpotify/sixDegrees"
)


// NeighborProviderMB fetches related artists from MusicBrainz.
func NeighborProviderMB(
	client *musicbrainz.Client,
	artist *sixdegrees.Artists,
	limit int,
	verbose bool,
) ([]sixdegrees.NeighborResult, int, error) {

	lookup, err := client.LookupArtist(
		artist.ID,
		"artist-rels",
		"recording-rels",
	)
	if err != nil {
		return nil, 500, err
	}

	relations := musicbrainz.ExtractCollaborators(lookup)

	out := make([]sixdegrees.NeighborResult, 0, len(relations))
	

	for _, r := range relations {
		nbArtist := &sixdegrees.Artists{
			ID:   r.ID,
			Name: r.Name,
		}

		// no track info unless extracted from recording relationships
		track := sixdegrees.Track{}

		out = append(out, sixdegrees.NeighborResult{
			Artist: nbArtist,
			Track:  track,
		})

		if limit > 0 && len(out) >= limit {
			break
		}
	}

	return out, 200, nil
}
