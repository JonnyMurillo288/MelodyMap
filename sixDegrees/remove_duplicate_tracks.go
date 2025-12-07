package sixdegrees

import (
	"fmt"
	"os"
	"regexp"
	"sort"
	"strings"
	"time"
	"unicode"

	"github.com/agext/levenshtein"
	"golang.org/x/text/unicode/norm"
)

// ------------------------------------
// Versioning / mix / noise info
// ------------------------------------

var versionNoise = []string{
	"album version",
	"single version",
	"radio edit",
	"clean edit",
	"clean version",
	"clean",
	"dirty",
	"explicit version",
	"explicit",
	"instrumental",
	"remix",
	"mix",
	"demo",
	"alternate version",
	"mastered",
	"original mix",
	"live at",
	"live in",
	"live",
	"a cappella",
	"acapella",
	"promo only",
}

func stripVersionTagsNorm(norm string) string {
	s := norm
	for _, tag := range versionNoise {
		if strings.Contains(s, tag) {
			s = strings.ReplaceAll(s, tag, " ")
		}
	}
	return strings.Join(strings.Fields(s), " ")
}

// ------------------------------------
// Normalizations
// ------------------------------------

var reStripPunctuation = regexp.MustCompile(`[.,:;(){}\[\]'"!?]`)
var reRomanNumeral = regexp.MustCompile(`\b(ii|iii|iv|v|vi|vii|viii|ix|x)\b`)

func stripDiacritics(s string) string {
	t := norm.NFD.String(s)
	out := make([]rune, 0, len(t))
	for _, r := range t {
		if unicode.IsMark(r) {
			continue
		}
		out = append(out, r)
	}
	return string(out)
}

func normalizeName(s string) string {
	s = strings.ToLower(s)
	s = stripDiacritics(s)

	replacements := map[string]string{
		" pt ":           " part ",
		"pt.":            " part ",
		"feat.":          " feat ",
		"featuring":      " feat ",
		"–":              "-",
		"—":              "-",
		"&":              " and ",
		"official video": "",
		"remastered":     "",
		"single version": "",
		"original mix":   "",
	}

	for k, v := range replacements {
		s = strings.ReplaceAll(s, k, v)
	}

	s = reStripPunctuation.ReplaceAllString(s, " ")

	s = reRomanNumeral.ReplaceAllStringFunc(s, func(m string) string {
		switch m {
		case "ii":
			return " 2"
		case "iii":
			return " 3"
		case "iv":
			return " 4"
		case "v":
			return " 5"
		case "vi":
			return " 6"
		case "vii":
			return " 7"
		case "viii":
			return " 8"
		case "ix":
			return " 9"
		case "x":
			return " 10"
		}
		return m
	})

	toks := strings.Fields(s)
	for i := 0; i < len(toks); i++ {
		if toks[i] == "pt" {
			toks[i] = "part"
		}
		if i+1 < len(toks) && toks[i] == "part" {
			switch toks[i+1] {
			case "ii", "two":
				toks[i+1] = "2"
			}
		}
	}
	s = strings.Join(toks, " ")

	return strings.Join(strings.Fields(s), " ")
}

// ------------------------------------
// Canon Structure
// ------------------------------------

type trackCanon struct {
	Raw        Track
	Norm       string
	Core       string
	Tokens     []string
	TokenSet   map[string]struct{}
	SortedCore string
}

func canonize(t Track) trackCanon {
	n := normalizeName(t.Name)
	core := stripVersionTagsNorm(n)

	toks := strings.Fields(core)
	tokenSet := make(map[string]struct{}, len(toks))
	for _, tok := range toks {
		tokenSet[tok] = struct{}{}
	}

	sorted := make([]string, len(toks))
	copy(sorted, toks)
	sort.Strings(sorted)
	sortedCore := strings.Join(sorted, " ")

	return trackCanon{
		Raw:        t,
		Norm:       n,
		Core:       core,
		Tokens:     toks,
		TokenSet:   tokenSet,
		SortedCore: sortedCore,
	}
}

// ------------------------------------
// Token Set Helpers
// ------------------------------------

func subsetSmall(short, long map[string]struct{}) bool {
	for tok := range short {
		if _, ok := long[tok]; !ok {
			return false
		}
	}
	return true
}

// ------------------------------------
// Fast Heuristic Equality
// ------------------------------------

func sameTrackFast(a, b trackCanon, threshold float64) bool {
	// 1) Strongest: PhotoURL
	if a.Raw.PhotoURL != "" && b.Raw.PhotoURL != "" &&
		a.Raw.PhotoURL == b.Raw.PhotoURL {
		return true
	}

	// 2) RecordingID
	if a.Raw.ID != "" && b.Raw.ID != "" &&
		a.Raw.ID == b.Raw.ID {
		return true
	}

	// 3) Core equality
	if a.Core == b.Core {
		return true
	}

	// 4) substring
	if strings.Contains(a.Core, b.Core) ||
		strings.Contains(b.Core, a.Core) {
		return true
	}

	// 5) Token multiset equality
	if a.SortedCore == b.SortedCore {
		return true
	}

	// 6) Token subset
	if subsetSmall(a.TokenSet, b.TokenSet) ||
		subsetSmall(b.TokenSet, a.TokenSet) {
		return true
	}

	// 7) fuzzy edit check
	if levenshtein.Similarity(a.Core, b.Core, nil) >= threshold {
		return true
	}

	return false
}

// ------------------------------------
// Canonical Choice
// ------------------------------------

func PickCanonical(
	a, b string,
	recIDA, recIDB string,
) (canonical string) {

	if recIDA != "" && recIDB != "" && recIDA == recIDB {
		if len(a) >= len(b) {
			return a
		}
		return b
	}
	if len(a) >= len(b) {
		return a
	}
	return b
}

// ------------------------------------
// Deduplicate
// ------------------------------------

func NowMillis() int64 {
	return time.Now().UnixNano() / int64(time.Millisecond)
}

// Track Performance Logging
const dedupeLogFile = "dedupe_perf_log.csv"

func ensureLogHeader() {
	_, err := os.Stat(dedupeLogFile)
	if err == nil {
		return // file exists
	}
	h := "ts,input_count,output_count,reduction_pct,threshold,elapsed_ms\n"
	_ = appendFile(dedupeLogFile, h)
}

// ------------------------------------
// Safe append to file
// ------------------------------------

func appendFile(path, content string) error {
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = f.WriteString(content)
	return err
}

func DeduplicateTracks(
	in []Track,
	sameThreshold float64,
	verbose bool,
) []Track {

	ensureLogHeader()

	startTime := NowMillis()

	// precompute all canonical forms
	canon := make([]trackCanon, len(in))
	for i, t := range in {
		canon[i] = canonize(t)
	}

	out := []trackCanon{}

	for _, c := range canon {
		found := false

		for i := range out {
			if sameTrackFast(out[i], c, sameThreshold) {
				// merge raw metadata
				out[i].Raw = mergeTracks(out[i].Raw, c.Raw)
				found = true
				break
			}
		}

		if !found {
			out = append(out, c)
		}
	}

	final := make([]Track, len(out))
	// if len(in) != len(out) {
	// 	fmt.Printf("Deduplicated tracks from %d to %d\n", len(in), len(out))
	// 	fmt.Printf(" Final tracks:\n")
	// 	for i, c := range out {
	// 		fmt.Printf("%d.  - %s\n", i+1, c.Raw.Name)
	// 	}
	// }
	for i, c := range out {
		final[i] = c.Raw
	}

	elapsed := NowMillis() - startTime
	reduction := float64(len(in)-len(out)) / float64(len(in)) * 100

	// Append metrics as CSV
	row := fmt.Sprintf(
		"%d,%d,%d,%.2f,%.3f,%d\n",
		time.Now().Unix(), // ts
		len(in),           // input_count
		len(out),          // output_count
		reduction,         // %
		sameThreshold,     // threshold used
		elapsed,           // ms
	)
	_ = appendFile(dedupeLogFile, row)
	return final
}

func mergeTracks(a, b Track) Track {
	if len(b.Name) > len(a.Name) {
		a.Name = b.Name
	}
	if a.ID == "" && b.ID != "" {
		a.ID = b.ID
	}
	if a.PhotoURL == "" && b.PhotoURL != "" {
		a.PhotoURL = b.PhotoURL
	}
	return a
}
