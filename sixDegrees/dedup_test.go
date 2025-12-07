package sixdegrees_test

import (
	"testing"

	sd "github.com/Jonnymurillo288/MelodyMap/sixDegrees"
)

// track helper
func T(name, id, photo string) sd.Track {
	return sd.Track{
		Name:     name,
		ID:       id,
		PhotoURL: photo,
	}
}

// requireNoDups ensures that no two tracks in the result set are
// still considered “same” according to the deduper logic.
// If the dedupe function leaves behind something that still qualifies
// as the same track, this will fail the test.
func requireNoDups(t *testing.T, tracks []sd.Track) {
	for i := 0; i < len(tracks); i++ {
		for j := i + 1; j < len(tracks); j++ {
			a := tracks[i]
			b := tracks[j]

			// We use the same threshold that the test passed into DeduplicateTracks.
			// If your tests use different thresholds, pass it in explicitly.
			if sd.IsLikelySameTrack(
				a.Name, b.Name,
				a.PhotoURL, b.PhotoURL,
				a.ID, b.ID,
				0.72, // same threshold your tests are using
			) {
				t.Fatalf(
					"Dedup left behind duplicates:\n A: %q (ID=%s Photo=%s)\n B: %q (ID=%s Photo=%s)",
					a.Name, a.ID, a.PhotoURL,
					b.Name, b.ID, b.PhotoURL,
				)
			}
		}
	}
}

// ------------------------------------------------------
// Basic sanity: identical names should dedupe
// ------------------------------------------------------

func TestDeduplicateTracks_IdenticalNames(t *testing.T) {
	in := []sd.Track{
		T("Airplanes", "1", ""),
		T("Airplanes", "1", ""),
	}

	out := sd.DeduplicateTracks(in, 0.72, false)
	if len(out) != 1 {
		t.Fatalf("Expected 1 after dedupe, got %d", len(out))
	}
	requireNoDups(t, out)

}

// ------------------------------------------------------
// Substring normalization
// ------------------------------------------------------

func TestDeduplicateTracks_SubstringCommon(t *testing.T) {
	in := []sd.Track{
		T("Airplanes (feat. Hayley Williams)", "aaa", ""),
		T("Airplanes", "aaa", ""),
		T("Airplanes – official video", "aaa", ""),
	}

	out := sd.DeduplicateTracks(in, 0.72, false)
	if len(out) != 1 {
		t.Fatalf("Expected 1 canonical track, got=%d", len(out))
	}
	requireNoDups(t, out)
}

// ------------------------------------------------------
// Roman numeral collapse
// ------------------------------------------------------

func TestDeduplicateTracks_RomanNumeral(t *testing.T) {
	in := []sd.Track{
		T("Symphony No. II", "x1", ""),
		T("Symphony No. 2", "x1", ""),
		T("Symphony No II", "x1", ""),
	}

	out := sd.DeduplicateTracks(in, 0.72, false)
	if len(out) != 1 {
		t.Fatalf("Expected 1 due to numeral normalization, got=%d", len(out))
	}
	requireNoDups(t, out)
}

// ------------------------------------------------------
// Recording ID should collapse even if titles differ
// ------------------------------------------------------

func TestDeduplicateTracks_RecordingIDPriority(t *testing.T) {
	in := []sd.Track{
		T("Forever (Remastered 2020)", "ABC", ""),
		T("Forever", "ABC", ""),
	}

	out := sd.DeduplicateTracks(in, 0.72, false)
	if len(out) != 1 {
		t.Fatalf("Recording ID match should force dedupe, got=%d", len(out))
	}
	requireNoDups(t, out)
}

// ------------------------------------------------------
// PhotoURL match should collapse
// ------------------------------------------------------

func TestDeduplicateTracks_PhotoURLPriority(t *testing.T) {
	in := []sd.Track{
		T("Song Alpha", "", "http://x"),
		T("Song Beta", "", "http://x"),
	}

	out := sd.DeduplicateTracks(in, 0.72, false)
	if len(out) != 1 {
		t.Fatalf("PhotoURL match should force dedupe, got=%d", len(out))
	}
	requireNoDups(t, out)
}

// ------------------------------------------------------
// Check canonical merging (longest wins)
// ------------------------------------------------------

func TestDeduplicateTracks_CanonicalMergeLongest(t *testing.T) {
	in := []sd.Track{
		T("Airplanes", "A", ""),
		T("Airplanes feat Hayley Williams", "A", ""),
	}

	out := sd.DeduplicateTracks(in, 0.72, false)

	if len(out) != 1 {
		t.Fatalf("Expected dedupe into 1, got=%d", len(out))
	}

	got := out[0].Name
	want := "Airplanes feat Hayley Williams"
	if got != want {
		t.Fatalf("Expected canonical=%q, got %q", want, got)
	}
	requireNoDups(t, out)
}

// ------------------------------------------------------
// Near-duplicates that should NOT merge
// (useful for debugging false positives)
// ------------------------------------------------------

func TestDeduplicateTracks_NotSimilarEnough(t *testing.T) {
	in := []sd.Track{
		T("Forever", "1", ""),
		T("Never Ever", "2", ""),
	}

	out := sd.DeduplicateTracks(in, 0.72, false)

	// Expect both retained
	if len(out) != 2 {
		t.Fatalf("Unexpected dedupe: expected 2, got=%d", len(out))
	}
	requireNoDups(t, out)
}

// ------------------------------------------------------
// Verbose run: easier debugging
// (paste massive cases into `in`)
// ------------------------------------------------------

func TestDeduplicateTracks_VerboseDebug(t *testing.T) {
	in := []sd.Track{
		// paste ANY large cluster you want to inspect
		// e.g. taylor swift remix variants
		// T("...", "...", "..."),
	}

	out := sd.DeduplicateTracks(in, 0.72, true)
	requireNoDups(t, out)

	// log retained items so you see final canonical choices
	for _, tr := range out {
		t.Logf("Final kept: %q  [ID=%s, Photo=%s]", tr.Name, tr.ID, tr.PhotoURL)
	}
}

func TestDeduplicateTracks_OutlierCluster(t *testing.T) {
	in := []sd.Track{
		// 1. DEAD WRONG cluster
		T("DEAD WRONG (Doctor Beez remix)", "1", "2"),
		T("DEAD WRONG (DA RENCH)", "1", "2"),
		T("DiedWronG (drenched out)", "1", "2"),

		// 2. Renegade cluster
		T("Renagade", "2", "3"),
		T("Da Renagade", "2", "3"),
		T("Renagades", "2", "3"),
		T("Renegade! (explicit)", "2", "3"),
		T("Renegade Part II", "2", "3"),

		// 3. Girl Gone Wild cluster
		T("Girl Gone Wild", "3", "4"),
		T("Girlgonewild", "3", "4"),
		T("Girls Gone Wild (Radio Edit)", "3", "4"),
		T("Girl Gone Wilde", "3", "4"),

		// 4. Stan cluster
		T("Stan (album version)", "4", "5"),
		T("STĀN", "4", "5"),
		T("Stan - Live at Grammys 2002", "4", "5"),
		T("Stan (explicit)", "4", "5"),
		T("Stan (Drum & Bass Mix)", "4", "5"),
		// 5. Hellbound cluster
		T("Hell Bound", "5", "6"),
		T("Hellbound", "5", "6"),
		T("Hell Bound - remix", "5", "6"),
		T("Hellbound! (Radio Edit)", "5", "6"),

		// 6. Bitch Please II cluster
		T("Bitch Please II", "6", "7"),
		T("Bitch Please 2", "6", "7"),
		T("Bxtch Pleaze II", "6", "7"),
		T("B**** Please II (Explicit)", "6", "7"),

		// 7. Just Rhymin with Proof cluster
		T("Just Rhymin' with Proof", "7", "8"),
		T("Just Rhymin with Proof", "7", "8"),
		T("Just Rhymin With Proof (Remastered 2018)", "7", "8"),
		T("Just Rhyming With Proof", "7", "8"),

		// 8. Love the Way You Lie cluster
		T("Love the Way You Lie", "8", "9"),
		T("Love The Way You Lie (explicit)", "8", "9"),
		T("Love the Way You Lie, Part II", "8", "9"),
		T("ラヴ・ザ・ウェイ・ユー・ライ", "8", "9"),
		T("Love the Way You Lie - album version", "8", "9"),

		// 9. 6 in the Morning cluster
		T("6 in the Mornin", "9", "10"),
		T("6 In The Morning", "9", "10"),
		T("Six in the Morning", "9", "10"),
		T("6 IN THE MORN'IN (Explicit)", "9", "10"),

		// 10. Lose Yourself cluster
		T("Lose Yourself", "10", "11"),
		T("Lose Yourself (Explicit)", "10", "11"),
		T("Lose Yourself – Live in Detroit 2009", "10", "11"),
		T("Lose Yourself - Remastered", "10", "11"),
		T("Løsé Yøürsélf", "10", "11"),
		T("Lose Yourself [Clean Version]", "10", "11"),
		T("LoseYourself", "10", "11"),
		T("Lose Yourself (Album Version)", "10", "11"),

		// 11. Cleanin' Out My Closet cluster
		T("Cleanin' Out My Closet", "11", "12"),
		T("Cleanin Out My Closet", "11", "12"),
		T("Cleanin Out My Closet - Radio Edit", "11", "12"),
		T("Cleaning Out My Closet", "11", "12"),
		T("Cleanin Out My Kl0set", "11", "12"),
		T("Cleanin' Out My Closet (Explicit)", "11", "12"),
		T("Cleanin-Out-My-Closet", "11", "12"),

		// 12. Mockingbird cluster
		T("Mockingbird", "12", "13"),
		T("Møckingbird", "12", "13"),
		T("Mockingbird (Album Version)", "12", "13"),
		T("Mocking Bird", "12", "13"),
		T("Mockinbird", "12", "13"),

		// 15. No Love cluster
		T("No Love", "15", "16"),
		T("No-Love", "15", "16"),
		T("Nō Love", "15", "16"),
		T("No Love (Explicit)", "15", "16"),
		T("No Love - album version", "15", "16"),
		T("NoLove", "15", "16"),

		// 10. Lose Yourself cluster
		T("Lose Yourself", "10", "11"),
		T("Lose Yourself (Explicit)", "10", "11"),
		T("Lose Yourself – Live in Detroit 2009", "10", "11"),
		T("Lose Yourself - Remastered", "10", "11"),
		T("Løsé Yøürsélf", "10", "11"),
		T("Lose Yourself [Clean Version]", "10", "11"),
		T("LoseYourself", "10", "11"),
		T("Lose Yourself (Album Version)", "10", "11"),

		// 11. Cleanin' Out My Closet cluster
		T("Cleanin' Out My Closet", "11", "12"),
		T("Cleanin Out My Closet", "11", "12"),
		T("Cleanin Out My Closet - Radio Edit", "11", "12"),
		T("Cleaning Out My Closet", "11", "12"),
		T("Cleanin Out My Kl0set", "11", "12"),
		T("Cleanin' Out My Closet (Explicit)", "11", "12"),
		T("Cleanin-Out-My-Closet", "11", "12"),

		// 12. Mockingbird cluster
		T("Mockingbird", "12", "13"),
		T("Møckingbird", "12", "13"),
		T("Mockingbird (Album Version)", "12", "13"),
		T("Mocking Bird", "12", "13"),
		T("Mockinbird", "12", "13"),

		// 13. The Real Slim Shady cluster
		T("The Real Slim Shady", "13", "14"),
		T("Real Slim Shady, The", "13", "14"),
		T("The Real Slim Shady (Remix)", "13", "14"),
		T("Real Slim Shady", "13", "14"),
		T("The Real Slim Shady - Album Version", "13", "14"),
		T("The Rēål Slim Shady", "13", "14"),
		T("RealSlimShady", "13", "14"),
		T("Shady Real Slim", "13", "14"),
		T("Slim, Shady (Real)", "13", "14"),

		// 14. Superman cluster
		T("Superman", "14", "15"),
		T("Superman (album version)", "14", "15"),
		T("Super Man", "14", "15"),
		T("Sūpērman", "14", "15"),

		// 15. No Love cluster
		T("No Love", "15", "16"),
		T("No-Love", "15", "16"),
		T("Nō Love", "15", "16"),
		T("No Love (Explicit)", "15", "16"),
		T("No Love - album version", "15", "16"),
		T("NoLove", "15", "16"),

		// 16. Kill You cluster
		T("Kill You", "16", "17"),
		T("Kill U", "16", "17"),
		T("Kill You (Explicit)", "16", "17"),
		T("Kill You - Clean Edit", "16", "17"),
		T("K1ll You", "16", "17"),

		// 17. When I'm Gone cluster
		T("When I'm Gone", "17", "18"),
		T("When Im Gone", "17", "18"),
		T("When I'm Gone - album version", "17", "18"),
		T("When I'm Gøne", "17", "18"),
		T("When Gone I'm", "17", "18"),

		// 18. Without Me cluster
		T("Without Me", "18", "19"),
		T("W1thout Me", "18", "19"),
		T("Wíthout Me", "18", "19"),
		T("Without Me - Remastered", "18", "19"),
		T("Without Me (Explicit Version)", "18", "19"),
		T("WithoutMe", "18", "19"),

		// 19. Lev Distance Misfire: Stan vs Scan (NOT SAME)
		T("Stan", "19", "20"),
		T("Scan", "19", "21"),

		// 20. Same Tokens But Different Song (NOT SAME)
		T("Lose Yourself", "20", "22"),
		T("Lose Yourself To Dance", "20", "23"),

		// 21. Renegade Trap (NOT SAME: Eminem vs Rage Against The Machine)
		T("Renegade", "21", "24"),
		T("Renegades", "21", "25"),

		// 22. 100 Mile vs 8 Mile (NOT SAME)
		T("8 Mile", "22", "26"),
		T("100 Mile Freestyle", "22", "27"),

		// 23. Without Me vs Without You (NOT SAME)
		T("Without Me", "23", "28"),
		T("Without You", "23", "29"),

		// 24. Love the Way You Lie — translation match (SHOULD MERGE)
		T("Love the Way You Lie", "24", "30"),
		T("ラヴ・ザ・ウェイ・ユー・ライ", "24", "30"),

		// 25. Way I Am Japanese variants (SHOULD MERGE)
		T("The Way I Am", "25", "31"),
		T("ザ・ウェイ・アイ・アム", "25", "31"),

		// 26. Different language but NOT translation (SHOULD NOT MERGE)
		T("Without Me", "26", "32"),
		T("Sin Mí", "26", "33"),

		// 27. Part II variants (SHOULD MERGE)
		T("Stan Part II", "27", "34"),
		T("Stan Pt. 2", "27", "34"),
		T("Stan II", "27", "34"),
		T("Stan (Part 2)", "27", "34"),
		T("Stan: Second Movement", "27", "34"),
		T("Stan Two", "27", "34"),
	}

	out := sd.DeduplicateTracks(in, 0.42, true)

	t.Logf("Original count: %d | After Dedupe: %d", len(in), len(out))
	for _, tr := range out {
		t.Logf("Kept: %q  [ID=%s, Photo=%s]", tr.Name, tr.ID, tr.PhotoURL)
	}

	// OPTIONAL if you expect total collapse:
	// if len(out) != 1 {
	// 	t.Fatalf("Expected full collapse to 1 canonical track, got %d", len(out))
	// }
}

func TestDeduplicateTracks_TransliterationCanonical(t *testing.T) {
	in := []sd.Track{
		T("Love the Way You Lie", "K", "W"),
		T("ラヴ・ザ・ウェイ・ユー・ライ", "K", "W"),
		T("Love the Way You Lie - album version", "K", "W"),
	}

	out := sd.DeduplicateTracks(in, 0.72, false)

	if len(out) != 1 {
		t.Fatalf("Expected collapse to 1 canonical track, got %d", len(out))
	}

	if out[0].Name != "Love the Way You Lie - album version" {
		t.Fatalf("Canonical wrong. got '%s'", out[0].Name)
	}
}
func TestDeduplicateTracks_CanonicalLongestTitle(t *testing.T) {
	in := []sd.Track{
		T("Lose Yourself", "Z", "Q"),
		T("Lose Yourself (Album Version)", "Z", "Q"),
		T("Lose Yourself – Live in Detroit 2009", "Z", "Q"),
	}

	out := sd.DeduplicateTracks(in, 0.72, false)

	if len(out) != 1 {
		t.Fatalf("Expected collapse to 1 canonical Lose Yourself")
	}

	want := "Lose Yourself – Live in Detroit 2009"
	if out[0].Name != want {
		t.Fatalf("Expected canonical '%s', got '%s'", want, out[0].Name)
	}
}
func TestDeduplicateTracks_PartTwoEquivalents(t *testing.T) {
	in := []sd.Track{
		T("Stan Part II", "S", "P"),
		T("Stan Pt. 2", "S", "P"),
		T("Stan II", "S", "P"),
		T("Stan (Part 2)", "S", "P"),
		T("Stan: Second Movement", "S", "P"),
		T("Stan Two", "S", "P"),
		T("Stan 2", "S", "P"),
	}

	out := sd.DeduplicateTracks(in, 0.72, false)

	if len(out) != 1 {
		t.Fatalf("Part II numerics did not collapse correctly: got %d", len(out))
	}
}
func TestDeduplicateTracks_CleaninCloset(t *testing.T) {
	in := []sd.Track{
		T("Cleanin' Out My Closet", "A", "B"),
		T("Cleanin Out My Closet - Radio Edit", "A", "B"),
		T("Cleaning Out My Closet", "A", "B"),
		T("Cleanin-Out-My-Closet", "A", "B"),
	}

	out := sd.DeduplicateTracks(in, 0.72, false)

	if len(out) != 1 {
		t.Fatalf("Cleanin closet cluster did not collapse fully: got %d", len(out))
	}
}
func TestDeduplicateTracks_TitleNoiseRemoval(t *testing.T) {
	in := []sd.Track{
		T("Lose Yourself", "L", "M"),
		T("Lose Yourself – Live in Detroit 2009", "L", "M"),
		T("Lose Yourself (Album Version)", "L", "M"),
		T("Lose Yourself (Explicit)", "L", "M"),
		T("Lose Yourself - Remastered", "L", "M"),
	}

	out := sd.DeduplicateTracks(in, 0.72, false)

	if len(out) != 1 {
		t.Fatalf("Noise-removal failed. Expected 1, got %d", len(out))
	}
}
func TestDeduplicateTracks_UnicodeFold(t *testing.T) {
	in := []sd.Track{
		T("Superman", "X", "Y"),
		T("Sūpērman", "X", "Y"),
		T("Súperman", "X", "Y"),
	}

	out := sd.DeduplicateTracks(in, 0.72, false)

	if len(out) != 1 {
		t.Fatalf("Unicode folding failed. Expected 1, got %d", len(out))
	}
}
