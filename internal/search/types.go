package search

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"sync"

	"github.com/lib/pq"
)

// TrackInfo used in path steps
type TrackInfo struct {
	ID            string `json:"id"`
	Name          string `json:"name"`
	RecordingID   string `json:"recordingID"`
	RecordingName string `json:"recordingName"`
	PhotoURL      string `json:"photoURL"`
}

// Step in the returned path
type Step struct {
	From   string      `json:"from"`
	To     string      `json:"to"`
	Tracks []TrackInfo `json:"tracks"`
	FromID string      `json:"fromID"`
	ToID   string      `json:"toID"`
}

// SearchResponse returned by background BFS and HTTP layer
type SearchResponse struct {
	Start    string `json:"start"`
	Target   string `json:"target"`
	StartID  string `json:"startID"`
	TargetID string `json:"targetID"`
	Hops     int    `json:"hops"`
	Path     []Step `json:"path"`
	Message  string `json:"message,omitempty"`
	Status   int    `json:"status"`
}

// Ticker for frontend live-updates
var SearchTicker = struct {
	Artist string `json:"artist"`
	Count  int    `json:"count"`
	Max    int    `json:"max"`
	Depth  int    `json:"depth"`
}{}

// Cached neighbors per artist for autocomplete expansion
var GlobalNeighborLookup = make(map[string]FrontendStep)
var TrackLookup = make(map[string]TrackFeatures)
var globalLookupMu sync.RWMutex

// What the UI expects when requesting neighbor lists
type FrontendStep struct {
	ID        string `json:"ID"`
	Name      string `json:"Name"`
	Neighbors []struct {
		ID     string      `json:"ID"`
		Name   string      `json:"Name"`
		Tracks []TrackInfo `json:"Tracks"`
	} `json:"Neighbors"`
}

// This is the track features dataset
type TrackFeatures struct {
	ID       string `json:"ID"`
	Name     string `json:"Name"`
	Features []TrackFeatures
}

// Internal BFS neighbor representation
type NeighborEdge struct {
	Artist *ArtistsWrapper
	Track  []TrackWrapper
	Link   string
}

type SearchRequest struct {
	Start    string `json:"start"`
	Target   string `json:"target"`
	StartID  string `json:"startID"`
	TargetID string `json:"targetID"`
	Depth    int    `json:"depth"`
}

type SearchResult struct {
	Response SearchResponse
	Error    error
}

// Minimal local wrappers to avoid sixdegrees import hell
type ArtistsWrapper struct {
	ID   string
	Name string
}

type TrackWrapper struct {
	ID            string
	Name          string
	RecordingID   string
	RecordingName string
	PhotoURL      string
}

type TrackDTO struct {
	ID            string `json:"id"`
	Name          string `json:"name"`
	RecordingID   string `json:"recordingID"`
	RecordingName string `json:"recordingName"`
	PhotoURL      string `json:"photoURL"`
}

// Helper functions for NullFloats to JSON Marshal as null
type NullFloat struct {
	sql.NullFloat64
}

func (nf NullFloat) MarshalJSON() ([]byte, error) {
	if !nf.Valid {
		return []byte("null"), nil
	}
	return json.Marshal(nf.Float64)
}

// For the backend lookup of track features
type RecordingFeatures struct {
	RecordingID   int64  `json:"recording_id"`
	RecordingGID  string `json:"recording_gid"`
	RecordingName string `json:"recording_name"`

	Danceability NullFloat `json:"danceability"`
	GenderFemale NullFloat `json:"gender_female"`
	GenderMale   NullFloat `json:"gender_male"`

	// --- genres ---
	GenreDortmundAlternative NullFloat `json:"genre_dortmund_alternative"`
	GenreDortmundBlues       NullFloat `json:"genre_dortmund_blues"`
	GenreDortmundElectronic  NullFloat `json:"genre_dortmund_electronic"`
	GenreDortmundFolkCountry NullFloat `json:"genre_dortmund_folkcountry"`
	GenreDortmundFunkSoulRnb NullFloat `json:"genre_dortmund_funksoulrnb"`
	GenreDortmundJazz        NullFloat `json:"genre_dortmund_jazz"`
	GenreDortmundPop         NullFloat `json:"genre_dortmund_pop"`
	GenreDortmundRapHipHop   NullFloat `json:"genre_dortmund_raphiphop"`
	GenreDortmundRock        NullFloat `json:"genre_dortmund_rock"`

	// --- electronic ---
	GenreElectronicAmbient NullFloat `json:"genre_electronic_ambient"`
	GenreElectronicDnb     NullFloat `json:"genre_electronic_dnb"`
	GenreElectronicHouse   NullFloat `json:"genre_electronic_house"`
	GenreElectronicTechno  NullFloat `json:"genre_electronic_techno"`
	GenreElectronicTrance  NullFloat `json:"genre_electronic_trance"`

	// --- rosamerica ---
	GenreRosamericaCla NullFloat `json:"genre_rosamerica_cla"`
	GenreRosamericaDan NullFloat `json:"genre_rosamerica_dan"`
	GenreRosamericaHip NullFloat `json:"genre_rosamerica_hip"`
	GenreRosamericaJaz NullFloat `json:"genre_rosamerica_jaz"`
	GenreRosamericaPop NullFloat `json:"genre_rosamerica_pop"`
	GenreRosamericaRhy NullFloat `json:"genre_rosamerica_rhy"`
	GenreRosamericaRoc NullFloat `json:"genre_rosamerica_roc"`
	GenreRosamericaSpe NullFloat `json:"genre_rosamerica_spe"`

	// --- tzanetakis ---
	GenreTzanetakisBlu NullFloat `json:"genre_tzanetakis_blu"`
	GenreTzanetakisCla NullFloat `json:"genre_tzanetakis_cla"`
	GenreTzanetakisCou NullFloat `json:"genre_tzanetakis_cou"`
	GenreTzanetakisDis NullFloat `json:"genre_tzanetakis_dis"`
	GenreTzanetakisHip NullFloat `json:"genre_tzanetakis_hip"`
	GenreTzanetakisJaz NullFloat `json:"genre_tzanetakis_jaz"`
	GenreTzanetakisMet NullFloat `json:"genre_tzanetakis_met"`
	GenreTzanetakisPop NullFloat `json:"genre_tzanetakis_pop"`
	GenreTzanetakisReg NullFloat `json:"genre_tzanetakis_reg"`
	GenreTzanetakisRoc NullFloat `json:"genre_tzanetakis_roc"`

	// --- rhythm ---
	RhythmChaChaCha          NullFloat `json:"ismir04_rhythm_chachacha"`
	RhythmJive               NullFloat `json:"ismir04_rhythm_jive"`
	RhythmQuickstep          NullFloat `json:"ismir04_rhythm_quickstep"`
	RhythmRumbaAmerican      NullFloat `json:"ismir04_rhythm_rumba_american"`
	RhythmRumbaInternational NullFloat `json:"ismir04_rhythm_rumba_international"`
	RhythmRumbaMisc          NullFloat `json:"ismir04_rhythm_rumba_misc"`
	RhythmSamba              NullFloat `json:"ismir04_rhythm_samba"`
	RhythmTango              NullFloat `json:"ismir04_rhythm_tango"`
	RhythmVienneseWaltz      NullFloat `json:"ismir04_rhythm_viennesewaltz"`
	RhythmWaltz              NullFloat `json:"ismir04_rhythm_waltz"`

	// --- mood ---
	MoodAcoustic   NullFloat `json:"mood_acoustic"`
	MoodAggressive NullFloat `json:"mood_aggressive"`
	MoodElectronic NullFloat `json:"mood_electronic"`
	MoodHappy      NullFloat `json:"mood_happy"`
	MoodParty      NullFloat `json:"mood_party"`
	MoodRelaxed    NullFloat `json:"mood_relaxed"`
	MoodSad        NullFloat `json:"mood_sad"`

	// --- mirex ---
	MirexCluster1 NullFloat `json:"moods_mirex_cluster1"`
	MirexCluster2 NullFloat `json:"moods_mirex_cluster2"`
	MirexCluster3 NullFloat `json:"moods_mirex_cluster3"`
	MirexCluster4 NullFloat `json:"moods_mirex_cluster4"`
	MirexCluster5 NullFloat `json:"moods_mirex_cluster5"`

	// --- timbre / tonal / voice ---
	TimbreBright NullFloat `json:"timbre_bright"`
	TimbreDark   NullFloat `json:"timbre_dark"`

	TonalAtonal NullFloat `json:"tonal_atonal_atonal"`
	TonalTonal  NullFloat `json:"tonal_atonal_tonal"`

	VoiceInstrumental NullFloat `json:"voice_instrumental_instrumental"`
	VoiceVocal        NullFloat `json:"voice_instrumental_voice"`
}

// GID : RecordingFeatures
type FrontendTracksList struct {
	FeaturesMap map[string]RecordingFeatures `json:"featuresMap"`
}

// SynthID : SyntheticRecordingFeatures
type SyntheticFrontendTracksList struct {
	FeaturesMap map[string]SyntheticRecordingFeatures `json:"featuresMap"`
}

// GetRecordingFeaturesByGIDs looks up audio / ML features for one or more recordings by MBID
func GetRecordingFeaturesByGIDs(
	ctx context.Context,
	store *Store,
	recordingGIDs []string,
) (map[string]RecordingFeatures, error) {

	if len(recordingGIDs) == 0 {
		return map[string]RecordingFeatures{}, nil
	}

	const query = `
		SELECT
			rf.recording_id,
			rf.recording_gid,
			r.name,
			rf.danceability,
			rf.gender_female,
			rf.gender_male,

			rf.genre_dortmund_alternative,
			rf.genre_dortmund_blues,
			rf.genre_dortmund_electronic,
			rf.genre_dortmund_folkcountry,
			rf.genre_dortmund_funksoulrnb,
			rf.genre_dortmund_jazz,
			rf.genre_dortmund_pop,
			rf.genre_dortmund_raphiphop,
			rf.genre_dortmund_rock,

			rf.genre_electronic_ambient,
			rf.genre_electronic_dnb,
			rf.genre_electronic_house,
			rf.genre_electronic_techno,
			rf.genre_electronic_trance,

			rf.genre_rosamerica_cla,
			rf.genre_rosamerica_dan,
			rf.genre_rosamerica_hip,
			rf.genre_rosamerica_jaz,
			rf.genre_rosamerica_pop,
			rf.genre_rosamerica_rhy,
			rf.genre_rosamerica_roc,
			rf.genre_rosamerica_spe,

			rf.genre_tzanetakis_blu,
			rf.genre_tzanetakis_cla,
			rf.genre_tzanetakis_cou,
			rf.genre_tzanetakis_dis,
			rf.genre_tzanetakis_hip,
			rf.genre_tzanetakis_jaz,
			rf.genre_tzanetakis_met,
			rf.genre_tzanetakis_pop,
			rf.genre_tzanetakis_reg,
			rf.genre_tzanetakis_roc,

			rf.ismir04_rhythm_chachacha,
			rf.ismir04_rhythm_jive,
			rf.ismir04_rhythm_quickstep,
			rf.ismir04_rhythm_rumba_american,
			rf.ismir04_rhythm_rumba_international,
			rf.ismir04_rhythm_rumba_misc,
			rf.ismir04_rhythm_samba,
			rf.ismir04_rhythm_tango,
			rf.ismir04_rhythm_viennesewaltz,
			rf.ismir04_rhythm_waltz,

			rf.mood_acoustic,
			rf.mood_aggressive,
			rf.mood_electronic,
			rf.mood_happy,
			rf.mood_party,
			rf.mood_relaxed,
			rf.mood_sad,

			rf.moods_mirex_cluster1,
			rf.moods_mirex_cluster2,
			rf.moods_mirex_cluster3,
			rf.moods_mirex_cluster4,
			rf.moods_mirex_cluster5,

			rf.timbre_bright,
			rf.timbre_dark,

			rf.tonal_atonal_atonal,
			rf.tonal_atonal_tonal,

			rf.voice_instrumental_instrumental,
			rf.voice_instrumental_voice
		FROM high_level_track_audio_features rf
		JOIN recording r
			ON rf.recording_id = r.id
		WHERE rf.recording_gid = ANY($1::uuid[]);
	`

	rows, err := store.DB.QueryContext(
		ctx,
		query,
		pq.Array(recordingGIDs),
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	results := make(map[string]RecordingFeatures, len(recordingGIDs))

	for rows.Next() {
		var f RecordingFeatures

		if err := rows.Scan(
			&f.RecordingID,
			&f.RecordingGID,
			&f.RecordingName,
			&f.Danceability,
			&f.GenderFemale,
			&f.GenderMale,

			&f.GenreDortmundAlternative,
			&f.GenreDortmundBlues,
			&f.GenreDortmundElectronic,
			&f.GenreDortmundFolkCountry,
			&f.GenreDortmundFunkSoulRnb,
			&f.GenreDortmundJazz,
			&f.GenreDortmundPop,
			&f.GenreDortmundRapHipHop,
			&f.GenreDortmundRock,

			&f.GenreElectronicAmbient,
			&f.GenreElectronicDnb,
			&f.GenreElectronicHouse,
			&f.GenreElectronicTechno,
			&f.GenreElectronicTrance,

			&f.GenreRosamericaCla,
			&f.GenreRosamericaDan,
			&f.GenreRosamericaHip,
			&f.GenreRosamericaJaz,
			&f.GenreRosamericaPop,
			&f.GenreRosamericaRhy,
			&f.GenreRosamericaRoc,
			&f.GenreRosamericaSpe,

			&f.GenreTzanetakisBlu,
			&f.GenreTzanetakisCla,
			&f.GenreTzanetakisCou,
			&f.GenreTzanetakisDis,
			&f.GenreTzanetakisHip,
			&f.GenreTzanetakisJaz,
			&f.GenreTzanetakisMet,
			&f.GenreTzanetakisPop,
			&f.GenreTzanetakisReg,
			&f.GenreTzanetakisRoc,

			&f.RhythmChaChaCha,
			&f.RhythmJive,
			&f.RhythmQuickstep,
			&f.RhythmRumbaAmerican,
			&f.RhythmRumbaInternational,
			&f.RhythmRumbaMisc,
			&f.RhythmSamba,
			&f.RhythmTango,
			&f.RhythmVienneseWaltz,
			&f.RhythmWaltz,

			&f.MoodAcoustic,
			&f.MoodAggressive,
			&f.MoodElectronic,
			&f.MoodHappy,
			&f.MoodParty,
			&f.MoodRelaxed,
			&f.MoodSad,

			&f.MirexCluster1,
			&f.MirexCluster2,
			&f.MirexCluster3,
			&f.MirexCluster4,
			&f.MirexCluster5,

			&f.TimbreBright,
			&f.TimbreDark,

			&f.TonalAtonal,
			&f.TonalTonal,

			&f.VoiceInstrumental,
			&f.VoiceVocal,
		); err != nil {
			return nil, err
		}

		results[f.RecordingGID] = f
	}

	if err := rows.Err(); err != nil {
		return nil, err
	}

	return results, nil
}

// ============================================
// Same as above, but for synthetic tracks retrieved from ML service
// ============================================

// For the backend lookup of track features
type SyntheticRecordingFeatures struct {
	SrcArtistID   string `json:"src_artist_id"`
	DstArtistID   string `json:"dst_artist_id,omitempty"`
	SrcArtistName string `json:"src_artist_name"`
	DstArtistName string `json:"dst_artist_name,omitempty"`
	TrackID       string `json:"track_id"`

	Danceability NullFloat `json:"danceability"`
	GenderFemale NullFloat `json:"gender_female"`
	GenderMale   NullFloat `json:"gender_male"`

	// --- genres ---
	GenreDortmundAlternative NullFloat `json:"genre_dortmund_alternative"`
	GenreDortmundBlues       NullFloat `json:"genre_dortmund_blues"`
	GenreDortmundElectronic  NullFloat `json:"genre_dortmund_electronic"`
	GenreDortmundFolkCountry NullFloat `json:"genre_dortmund_folkcountry"`
	GenreDortmundFunkSoulRnb NullFloat `json:"genre_dortmund_funksoulrnb"`
	GenreDortmundJazz        NullFloat `json:"genre_dortmund_jazz"`
	GenreDortmundPop         NullFloat `json:"genre_dortmund_pop"`
	GenreDortmundRapHipHop   NullFloat `json:"genre_dortmund_raphiphop"`
	GenreDortmundRock        NullFloat `json:"genre_dortmund_rock"`

	// --- electronic ---
	GenreElectronicAmbient NullFloat `json:"genre_electronic_ambient"`
	GenreElectronicDnb     NullFloat `json:"genre_electronic_dnb"`
	GenreElectronicHouse   NullFloat `json:"genre_electronic_house"`
	GenreElectronicTechno  NullFloat `json:"genre_electronic_techno"`
	GenreElectronicTrance  NullFloat `json:"genre_electronic_trance"`

	// --- rosamerica ---
	GenreRosamericaCla NullFloat `json:"genre_rosamerica_cla"`
	GenreRosamericaDan NullFloat `json:"genre_rosamerica_dan"`
	GenreRosamericaHip NullFloat `json:"genre_rosamerica_hip"`
	GenreRosamericaJaz NullFloat `json:"genre_rosamerica_jaz"`
	GenreRosamericaPop NullFloat `json:"genre_rosamerica_pop"`
	GenreRosamericaRhy NullFloat `json:"genre_rosamerica_rhy"`
	GenreRosamericaRoc NullFloat `json:"genre_rosamerica_roc"`
	GenreRosamericaSpe NullFloat `json:"genre_rosamerica_spe"`

	// --- tzanetakis ---
	GenreTzanetakisBlu NullFloat `json:"genre_tzanetakis_blu"`
	GenreTzanetakisCla NullFloat `json:"genre_tzanetakis_cla"`
	GenreTzanetakisCou NullFloat `json:"genre_tzanetakis_cou"`
	GenreTzanetakisDis NullFloat `json:"genre_tzanetakis_dis"`
	GenreTzanetakisHip NullFloat `json:"genre_tzanetakis_hip"`
	GenreTzanetakisJaz NullFloat `json:"genre_tzanetakis_jaz"`
	GenreTzanetakisMet NullFloat `json:"genre_tzanetakis_met"`
	GenreTzanetakisPop NullFloat `json:"genre_tzanetakis_pop"`
	GenreTzanetakisReg NullFloat `json:"genre_tzanetakis_reg"`
	GenreTzanetakisRoc NullFloat `json:"genre_tzanetakis_roc"`

	// --- rhythm ---
	RhythmChaChaCha          NullFloat `json:"ismir04_rhythm_chachacha"`
	RhythmJive               NullFloat `json:"ismir04_rhythm_jive"`
	RhythmQuickstep          NullFloat `json:"ismir04_rhythm_quickstep"`
	RhythmRumbaAmerican      NullFloat `json:"ismir04_rhythm_rumba_american"`
	RhythmRumbaInternational NullFloat `json:"ismir04_rhythm_rumba_international"`
	RhythmRumbaMisc          NullFloat `json:"ismir04_rhythm_rumba_misc"`
	RhythmSamba              NullFloat `json:"ismir04_rhythm_samba"`
	RhythmTango              NullFloat `json:"ismir04_rhythm_tango"`
	RhythmVienneseWaltz      NullFloat `json:"ismir04_rhythm_viennesewaltz"`
	RhythmWaltz              NullFloat `json:"ismir04_rhythm_waltz"`

	// --- mood ---
	MoodAcoustic   NullFloat `json:"mood_acoustic"`
	MoodAggressive NullFloat `json:"mood_aggressive"`
	MoodElectronic NullFloat `json:"mood_electronic"`
	MoodHappy      NullFloat `json:"mood_happy"`
	MoodParty      NullFloat `json:"mood_party"`
	MoodRelaxed    NullFloat `json:"mood_relaxed"`
	MoodSad        NullFloat `json:"mood_sad"`

	// --- mirex ---
	MirexCluster1 NullFloat `json:"moods_mirex_cluster1"`
	MirexCluster2 NullFloat `json:"moods_mirex_cluster2"`
	MirexCluster3 NullFloat `json:"moods_mirex_cluster3"`
	MirexCluster4 NullFloat `json:"moods_mirex_cluster4"`
	MirexCluster5 NullFloat `json:"moods_mirex_cluster5"`

	// --- timbre / tonal / voice ---
	TimbreBright NullFloat `json:"timbre_bright"`
	TimbreDark   NullFloat `json:"timbre_dark"`

	TonalAtonal NullFloat `json:"tonal_atonal_atonal"`
	TonalTonal  NullFloat `json:"tonal_atonal_tonal"`

	VoiceInstrumental NullFloat `json:"voice_instrumental_instrumental"`
	VoiceVocal        NullFloat `json:"voice_instrumental_voice"`
}

// GID : RecordingFeatures
type FrontendSyntheticTracksList struct {
	FeaturesMap map[string]SyntheticRecordingFeatures `json:"featuresMap"`
}

// GetSyntheticTrackFeaturesByGIDs looks up audio / ML features for one or more recordings by MBID
func GetSyntheticTrackFeaturesByGIDs(
	ctx context.Context,
	store *Store,
	trackIDs []int, limit int,
) (map[string]SyntheticRecordingFeatures, error) {
	// This returns a map

	// THE DATABASES ARE NOT CREATED YET, DO THIS FIRST
	// CREATE TABLE synthetic_tracks_high_level_features AS TABLE high_level_track_audio_features WITH NO DATA;
	// CREATE TABLE synthetic_tracks AS TABLE tracks WITH NO DATA;
	// Then populate synthetic_tracks with the tracks returned from the ML service
	if len(trackIDs) == 0 {
		fmt.Println("GetSyntheticTrackFeaturesByGIDs: no track IDs provided")
		return map[string]SyntheticRecordingFeatures{}, nil
	}

	const query = `
		SELECT
			r.src_artist_id,
			r.dst_artist_id,
			a1.name AS src_artist_name,
			a2.name AS dst_artist_name,
			r.track_id,

			rf.danceability,
			rf.gender_female,
			rf.gender_male,

			rf.genre_dortmund_alternative,
			rf.genre_dortmund_blues,
			rf.genre_dortmund_electronic,
			rf.genre_dortmund_folkcountry,
			rf.genre_dortmund_funksoulrnb,
			rf.genre_dortmund_jazz,
			rf.genre_dortmund_pop,
			rf.genre_dortmund_raphiphop,
			rf.genre_dortmund_rock,

			rf.genre_electronic_ambient,
			rf.genre_electronic_dnb,
			rf.genre_electronic_house,
			rf.genre_electronic_techno,
			rf.genre_electronic_trance,

			rf.genre_rosamerica_cla,
			rf.genre_rosamerica_dan,
			rf.genre_rosamerica_hip,
			rf.genre_rosamerica_jaz,
			rf.genre_rosamerica_pop,
			rf.genre_rosamerica_rhy,
			rf.genre_rosamerica_roc,
			rf.genre_rosamerica_spe,

			rf.genre_tzanetakis_blu,
			rf.genre_tzanetakis_cla,
			rf.genre_tzanetakis_cou,
			rf.genre_tzanetakis_dis,
			rf.genre_tzanetakis_hip,
			rf.genre_tzanetakis_jaz,
			rf.genre_tzanetakis_met,
			rf.genre_tzanetakis_pop,
			rf.genre_tzanetakis_reg,
			rf.genre_tzanetakis_roc,

			rf.ismir04_rhythm_chachacha,
			rf.ismir04_rhythm_jive,
			rf.ismir04_rhythm_quickstep,
			rf.ismir04_rhythm_rumba_american,
			rf.ismir04_rhythm_rumba_international,
			rf.ismir04_rhythm_rumba_misc,
			rf.ismir04_rhythm_samba,
			rf.ismir04_rhythm_tango,
			rf.ismir04_rhythm_viennesewaltz,
			rf.ismir04_rhythm_waltz,

			rf.mood_acoustic,
			rf.mood_aggressive,
			rf.mood_electronic,
			rf.mood_happy,
			rf.mood_party,
			rf.mood_relaxed,
			rf.mood_sad,

			rf.moods_mirex_cluster1,
			rf.moods_mirex_cluster2,
			rf.moods_mirex_cluster3,
			rf.moods_mirex_cluster4,
			rf.moods_mirex_cluster5,

			rf.timbre_bright,
			rf.timbre_dark,

			rf.tonal_atonal_atonal,
			rf.tonal_atonal_tonal,

			rf.voice_instrumental_instrumental,
			rf.voice_instrumental_voice
		FROM synthetic_tracks r
		JOIN synthetic_tracks_high_level_features rf
			ON rf.track_id = r.track_id
		JOIN artist a1
			ON r.src_artist_id = a1.id
		LEFT JOIN artist a2
			ON r.dst_artist_id = a2.id
		WHERE rf.track_id = ANY($1)
		LIMIT $2;
	`

	rows, err := store.DB.QueryContext(
		ctx,
		query,
		trackIDs, limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	results := make(map[string]SyntheticRecordingFeatures, limit)

	for rows.Next() {
		var f SyntheticRecordingFeatures

		if err := rows.Scan(
			&f.SrcArtistID,
			&f.DstArtistID,
			&f.SrcArtistName,
			&f.DstArtistName,
			&f.TrackID,
			&f.Danceability,
			&f.GenderFemale,
			&f.GenderMale,

			&f.GenreDortmundAlternative,
			&f.GenreDortmundBlues,
			&f.GenreDortmundElectronic,
			&f.GenreDortmundFolkCountry,
			&f.GenreDortmundFunkSoulRnb,
			&f.GenreDortmundJazz,
			&f.GenreDortmundPop,
			&f.GenreDortmundRapHipHop,
			&f.GenreDortmundRock,

			&f.GenreElectronicAmbient,
			&f.GenreElectronicDnb,
			&f.GenreElectronicHouse,
			&f.GenreElectronicTechno,
			&f.GenreElectronicTrance,

			&f.GenreRosamericaCla,
			&f.GenreRosamericaDan,
			&f.GenreRosamericaHip,
			&f.GenreRosamericaJaz,
			&f.GenreRosamericaPop,
			&f.GenreRosamericaRhy,
			&f.GenreRosamericaRoc,
			&f.GenreRosamericaSpe,

			&f.GenreTzanetakisBlu,
			&f.GenreTzanetakisCla,
			&f.GenreTzanetakisCou,
			&f.GenreTzanetakisDis,
			&f.GenreTzanetakisHip,
			&f.GenreTzanetakisJaz,
			&f.GenreTzanetakisMet,
			&f.GenreTzanetakisPop,
			&f.GenreTzanetakisReg,
			&f.GenreTzanetakisRoc,

			&f.RhythmChaChaCha,
			&f.RhythmJive,
			&f.RhythmQuickstep,
			&f.RhythmRumbaAmerican,
			&f.RhythmRumbaInternational,
			&f.RhythmRumbaMisc,
			&f.RhythmSamba,
			&f.RhythmTango,
			&f.RhythmVienneseWaltz,
			&f.RhythmWaltz,

			&f.MoodAcoustic,
			&f.MoodAggressive,
			&f.MoodElectronic,
			&f.MoodHappy,
			&f.MoodParty,
			&f.MoodRelaxed,
			&f.MoodSad,

			&f.MirexCluster1,
			&f.MirexCluster2,
			&f.MirexCluster3,
			&f.MirexCluster4,
			&f.MirexCluster5,

			&f.TimbreBright,
			&f.TimbreDark,

			&f.TonalAtonal,
			&f.TonalTonal,

			&f.VoiceInstrumental,
			&f.VoiceVocal,
		); err != nil {
			return nil, err
		}

		results[f.TrackID] = f
	}

	if err := rows.Err(); err != nil {
		return nil, err
	}

	return results, nil
}

// ===========================================
// Cached Synthetic Neighbor Lookup
// ===========================================

// CachedNeighbor represents a previously-computed synthetic neighbor stored in the DB.
type CachedNeighbor struct {
	DstArtistGID  string  `json:"dst_artist_id"`
	DstArtistName string  `json:"dst_artist_name"`
	TrackIDs      []int   `json:"tracks"`
	Probability   float64 `json:"probability"`
}

// GetCachedSynthNeighbors checks the synthetic_tracks table for existing predictions
// for the given source artist. Returns nil (not an error) if no cached data exists.
// Includes the link prediction probability from synthetic_tracks_high_level_features.
func GetCachedSynthNeighbors(ctx context.Context, store *Store, srcArtistID int, limit int) ([]CachedNeighbor, error) {
	const query = `
		SELECT
			a.gid::text  AS dst_artist_gid,
			a.name       AS dst_artist_name,
			array_agg(st.track_id ORDER BY st.track_id) AS track_ids,
			COALESCE(MAX(shlf.prob), 0) AS probability
		FROM synthetic_tracks st
		JOIN artist a ON a.id = st.dst_artist_id
		LEFT JOIN synthetic_tracks_high_level_features shlf ON shlf.track_id = st.track_id
		WHERE st.src_artist_id = $1
		GROUP BY a.gid, a.name
		ORDER BY COALESCE(MAX(shlf.prob), 0) DESC
		LIMIT $2;
	`

	rows, err := store.DB.QueryContext(ctx, query, srcArtistID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var results []CachedNeighbor
	for rows.Next() {
		var cn CachedNeighbor
		if err := rows.Scan(&cn.DstArtistGID, &cn.DstArtistName, pq.Array(&cn.TrackIDs), &cn.Probability); err != nil {
			return nil, err
		}
		results = append(results, cn)
	}
	return results, rows.Err()
}

// ===========================================
// Migration of the SytheticTrack Databases
// ===========================================

// InitSyntheticTrackTables creates required synthetic tables if they do not exist.
// Safe to call on startup.
func InitSyntheticTrackTables(ctx context.Context, store *Store) error {
	fmt.Println("Going to initialize the synthetic Track Tables")
	const ddl = `
		-- ---------------------------------------------------------------
		-- Synthetic tracks (multiple tracks per src-dst pair allowed)
		-- ---------------------------------------------------------------
		CREATE TABLE IF NOT EXISTS synthetic_tracks (
			track_id INT GENERATED ALWAYS AS IDENTITY,
			src_artist_id INT NOT NULL,
			dst_artist_id INT NOT NULL,

			CONSTRAINT synthetic_tracks_pkey
				PRIMARY KEY (track_id)
		);

		-- Drop old UNIQUE constraint if it exists (allows multiple tracks per pair)
		ALTER TABLE synthetic_tracks
			DROP CONSTRAINT IF EXISTS synthetic_tracks_src_dst_unique;

		-- ---------------------------------------------------------------
		-- Synthetic track high-level features
		-- ---------------------------------------------------------------
		CREATE TABLE IF NOT EXISTS synthetic_tracks_high_level_features (
			LIKE high_level_track_audio_features INCLUDING ALL
		);

		ALTER TABLE synthetic_tracks_high_level_features
			DROP COLUMN IF EXISTS recording_id,
			DROP COLUMN IF EXISTS recording_gid,
			DROP COLUMN IF EXISTS recording_name;

		ALTER TABLE synthetic_tracks_high_level_features
			ADD COLUMN IF NOT EXISTS track_id INT NOT NULL;

		-- Add prob column for storing link prediction probability
		ALTER TABLE synthetic_tracks_high_level_features
			ADD COLUMN IF NOT EXISTS prob FLOAT;

		DO $$ BEGIN
			ALTER TABLE synthetic_tracks_high_level_features
				ADD CONSTRAINT synthetic_tracks_high_level_features_pkey
				PRIMARY KEY (track_id);
		EXCEPTION WHEN duplicate_object THEN NULL;
		END $$;

		DO $$ BEGIN
			ALTER TABLE synthetic_tracks_high_level_features
				ADD CONSTRAINT synthetic_tracks_features_track_fk
				FOREIGN KEY (track_id)
				REFERENCES synthetic_tracks (track_id)
				ON DELETE CASCADE;
		EXCEPTION WHEN duplicate_object THEN NULL;
		END $$;

		-- ---------------------------------------------------------------
		-- Synthetic track model versioning
		-- ---------------------------------------------------------------
		CREATE TABLE IF NOT EXISTS synthetic_track_model_versions (
			track_id INT NOT NULL,
			model_name TEXT NOT NULL,
			version TEXT NOT NULL,
			created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
		);

		DO $$ BEGIN
			ALTER TABLE synthetic_track_model_versions
				ADD CONSTRAINT synthetic_track_model_versions_track_fk
				FOREIGN KEY (track_id)
				REFERENCES synthetic_tracks (track_id)
				ON DELETE CASCADE;
		EXCEPTION WHEN duplicate_object THEN NULL;
		END $$;
	`

	_, err := store.DB.ExecContext(ctx, ddl)
	return err
}
