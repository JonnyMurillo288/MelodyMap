# Spotle

## Description
This is an implementation to Wordle with my Melody-Map/Interlude. 
Connect the graph data, synthetic connections, and synthetic tracks to get a synthetic playlist and try to guess the input artist that was created. 

### Interlude

**Objective (`y`)**  
Predict whether a **collaboration link** exists between a source artist (`src`) and a destination artist (`dst`) in the collaboration graph.

For potential connections, estimate potential connections that do not exist. Example Eminem -> Taylor Swift
Then create `synthetic_tracks` for said potential connection. And lastly create a synthetic playlist based on existing tracks similar to what Taylor Swift already has created.

---

## Prediction Flow

```text
1. Predict Links
     |
     |-- No  → Why does a collaboration NOT occur?
     |
     |-- Yes
           |
           v
    2. Predict Track
           |
           v
    3. Track Popularity
           |
           v
Track Popularity − Avg(Track Popularity)
```
---

### Interlude to Melody-Map Integration
#### Purpose
Not only can we show the user the existing artist connections, and do that in a map format. But we can also show the user "potential" matches that could have existed, based on the above model

#### Logic
User inputs an artist, the Interlude service does the following:
1. Display all existing artist connections and the track features of said existing connections
2. Collect and display predicted artist connections. 
    EX. Eminem and Taylor Swift do not have a track together. 
    The goal of Interlude is to both predict the probability that they would have a song together AND what those track features would look like (Dancibility, Genre, Mood, etc.). These tracks are `synthetic_tracks`

3. From here, allow the user to click on a list of `synthetic_tracks` and use those track features to other `true_tracks` to a similarity matching creating a list of `true_tracks` that match best to `synthetic_tracks`
4. Create a `synthetic_playlist` from the user selected `synthetic_tracks`.
5. OR
   Create the `synthetic_playlist` for the user, selecting the best `x` # of `synthetic_tracks`

### Spotle Integration 
Spotle is a version of Wordle, but with music artists. Where user guesses
- Genre - Gender 
- -Debut -Rank 
- -Nationality 
Trying to guess the daily artist.

#### Purpose
With the above Interlude playlist, create a daily playlist from an input artist. Send this to a user's Spotify (or Apple Music??) daily. Making them (hopefully) more likely to use the service.  

They will get a daily playlist based on user's selected genre(s). With the genre(s) we can create a daily playlist and daily puzzle. 