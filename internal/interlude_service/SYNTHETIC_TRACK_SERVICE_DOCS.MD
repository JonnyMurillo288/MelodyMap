# This is the Documentation of the backend ML service hosted in our Docker

## The purpose of this is to keep track of the modules that we have and how they communicate with the frontend

### 1. Backend service:
a. ml/synth/artist
This finds our synthetic artist to artist connections

b. ml/synth/tracks
This creates a unique synthetic track object that have track features created by the CVAE model

This will be similar to table1 actual high level audio features and same format as `featuresMap` in STEP 4 of the js event listener

Look at Object `TrackFeaturesDisplay` in ml_pagev2_table_change.js

"""
Object { recording_id: 13911600, recording_gid: "3b49559e-07c7-46c2-b77f-1cae2878ee7d", recording_name: "Our House", danceability: 0.941033482552, gender_female: 0.0650923401117, gender_male: 0.934907674789, genre_dortmund_alternative: 1.36736466594e-9, genre_dortmund_blues: 1.56528612294e-9, genre_dortmund_electronic: 0.999998211861, genre_dortmund_folkcountry: 4.42503107934e-7, … }

"""