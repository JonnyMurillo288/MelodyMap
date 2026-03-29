

-- Need to create a new SQL that is the count of genres for each artist
-- To do this we will need to join the high_level_track_audio_features to their respective recording through mbid
-- Then join that recording to the artist
-- Then we will have to find a way to classify the genres into high level generes
-- Then we can get the count of each genres recordings for each artist
-- Then get the proportion of each genre for each artist 

-- The way this goes is for Dortmund, Electronic, Rosamerica, Tzanetakis
-- Each of these datasets have their own genre classifications that sum up to 1
-- So we can sum up the totals from each recording for each artist
-- Then with the summed up proportion totals we can create relative proportions for each genre
-- So the final table will be those genres below, with the proportion of that genre for that artist
-- Dortmund, Electronic, Rosamerica, Tzanetakis all = 1 when summed up
-- But the proportions are their relative proportions for that artist

/*
Dortmund                      Electronic                    Rosamerica                    Tzanetakis
genre_dortmund_alternative    genre_electronic_ambient      genre_rosamerica_cla          genre_tzanetakis_blu
genre_dortmund_blues          genre_electronic_dnb          genre_rosamerica_dan          genre_tzanetakis_cla
genre_dortmund_electronic     genre_electronic_house        genre_rosamerica_hip          genre_tzanetakis_cou
genre_dortmund_folkcountry    genre_electronic_techno       genre_rosamerica_jaz          genre_tzanetakis_dis
genre_dortmund_funksoulrnb    genre_electronic_trance       genre_rosamerica_pop          genre_tzanetakis_hip
genre_dortmund_jazz                                         genre_rosamerica_rhy          genre_tzanetakis_jaz
genre_dortmund_pop                                          genre_rosamerica_roc          genre_tzanetakis_met
genre_dortmund_raphiphop                                    genre_rosamerica_spe          genre_tzanetakis_pop
genre_dortmund_rock                                                                       genre_tzanetakis_reg
                                                                                          genre_tzanetakis_roc
*/


/*
    genre_dortmund_alternative,
    genre_dortmund_blues,
    genre_dortmund_electronic,
    genre_dortmund_folkcountry,
    genre_dortmund_funksoulrnb,
    genre_dortmund_jazz,
    genre_dortmund_pop,
    genre_dortmund_raphiphop,
    genre_dortmund_rock,
    genre_electronic_ambient,
    genre_electronic_dnb,
    genre_electronic_house,
    genre_electronic_techno,
    genre_electronic_trance,
    genre_rosamerica_cla,
    genre_rosamerica_dan,
    genre_rosamerica_hip,
    genre_rosamerica_jaz,
    genre_rosamerica_pop,
    genre_rosamerica_rhy,
    genre_rosamerica_roc,
    genre_rosamerica_spe,
    genre_tzanetakis_blu,
    genre_tzanetakis_cla,
    genre_tzanetakis_cou,
    genre_tzanetakis_dis,
    genre_tzanetakis_hip,
    genre_tzanetakis_jaz,
    genre_tzanetakis_met,
    genre_tzanetakis_pop,
    genre_tzanetakis_reg,
    genre_tzanetakis_roc

*/

-- select * from high_level_track_audio_features limit 5;


-- First join the high_level_track_audio_features to recording then join that to artist through the l_artist_recording table
DROP TABLE IF EXISTS artist_genre_proportions;
CREATE TABLE artist_genre_proportions AS
WITH artist_recordings AS (
    SELECT 
        l.entity0 AS artist_id, 
        l.entity1 AS recording_id,
        hlaf.*,
        COUNT(hlaf.recording_gid) OVER(PARTITION BY l.entity0) AS recording_count
    FROM l_artist_recording l 
    JOIN high_level_track_audio_features hlaf
        ON l.entity1 = hlaf.recording_id
), 
genre_totals AS (
    SELECT
        artist_id,
        -- Dortmund genres
        SUM(genre_dortmund_alternative) AS sum_genre_dortmund_alternative,
        SUM(genre_dortmund_blues) AS sum_genre_dortmund_blues,
        SUM(genre_dortmund_electronic) AS sum_genre_dortmund_electronic,
        SUM(genre_dortmund_folkcountry) AS sum_genre_dortmund_folkcountry,
        SUM(genre_dortmund_funksoulrnb) AS sum_genre_dortmund_funksoulrnb,
        SUM(genre_dortmund_jazz) AS sum_genre_dortmund_jazz,
        SUM(genre_dortmund_pop) AS sum_genre_dortmund_pop,
        SUM(genre_dortmund_raphiphop) AS sum_genre_dortmund_raphiphop,
        SUM(genre_dortmund_rock) AS sum_genre_dortmund_rock,
        -- Electronic genres
        SUM(genre_electronic_ambient) AS sum_genre_electronic_ambient,
        SUM(genre_electronic_dnb) AS sum_genre_electronic_dnb,
        SUM(genre_electronic_house) AS sum_genre_electronic_house,
        SUM(genre_electronic_techno) AS sum_genre_electronic_techno,
        SUM(genre_electronic_trance) AS sum_genre_electronic_trance,
        -- Rosamerica genres
        SUM(genre_rosamerica_cla) AS sum_genre_rosamerica_cla,
        SUM(genre_rosamerica_dan) AS sum_genre_rosamerica_dan,
        SUM(genre_rosamerica_hip) AS sum_genre_rosamerica_hip,
        SUM(genre_rosamerica_jaz) AS sum_genre_rosamerica_jaz,
        SUM(genre_rosamerica_pop) AS sum_genre_rosamerica_pop,
        SUM(genre_rosamerica_rhy) AS sum_genre_rosamerica_rhy,
        SUM(genre_rosamerica_roc) AS sum_genre_rosamerica_roc,
        SUM(genre_rosamerica_spe) AS sum_genre_rosamerica_spe,
        -- Tzanetakis genres
        SUM(genre_tzanetakis_blu) AS sum_genre_tzanetakis_blu,
        SUM(genre_tzanetakis_cla) AS sum_genre_tzanetakis_cla,
        SUM(genre_tzanetakis_cou) AS sum_genre_tzanetakis_cou,
        SUM(genre_tzanetakis_dis) AS sum_genre_tzanetakis_dis,
        SUM(genre_tzanetakis_hip) AS sum_genre_tzanetakis_hip,
        SUM(genre_tzanetakis_jaz) AS sum_genre_tzanetakis_jaz,
        SUM(genre_tzanetakis_met) AS sum_genre_tzanetakis_met,
        SUM(genre_tzanetakis_pop) AS sum_genre_tzanetakis_pop,
        SUM(genre_tzanetakis_reg) AS sum_genre_tzanetakis_reg,
        SUM(genre_tzanetakis_roc) AS sum_genre_tzanetakis_roc,
        -- Calculate totals for each genre group
        (SUM(genre_dortmund_alternative) + SUM(genre_dortmund_blues) + SUM(genre_dortmund_electronic) + 
         SUM(genre_dortmund_folkcountry) + SUM(genre_dortmund_funksoulrnb) + SUM(genre_dortmund_jazz) + 
         SUM(genre_dortmund_pop) + SUM(genre_dortmund_raphiphop) + SUM(genre_dortmund_rock)) AS total_dortmund,
        (SUM(genre_electronic_ambient) + SUM(genre_electronic_dnb) + SUM(genre_electronic_house) + 
         SUM(genre_electronic_techno) + SUM(genre_electronic_trance)) AS total_electronic,
        (SUM(genre_rosamerica_cla) + SUM(genre_rosamerica_dan) + SUM(genre_rosamerica_hip) + 
         SUM(genre_rosamerica_jaz) + SUM(genre_rosamerica_pop) + SUM(genre_rosamerica_rhy) + 
         SUM(genre_rosamerica_roc) + SUM(genre_rosamerica_spe)) AS total_rosamerica,
        (SUM(genre_tzanetakis_blu) + SUM(genre_tzanetakis_cla) + SUM(genre_tzanetakis_cou) + 
         SUM(genre_tzanetakis_dis) + SUM(genre_tzanetakis_hip) + SUM(genre_tzanetakis_jaz) + 
         SUM(genre_tzanetakis_met) + SUM(genre_tzanetakis_pop) + SUM(genre_tzanetakis_reg) + 
         SUM(genre_tzanetakis_roc)) AS total_tzanetakis
    FROM artist_recordings
    GROUP BY artist_id
)
SELECT -- This returns the artists genre proportions
    artist_id,
    -- Dortmund proportions
    sum_genre_dortmund_alternative / NULLIF(total_dortmund, 0) AS prop_genre_dortmund_alternative,
    sum_genre_dortmund_blues / NULLIF(total_dortmund, 0) AS prop_genre_dortmund_blues,
    sum_genre_dortmund_electronic / NULLIF(total_dortmund, 0) AS prop_genre_dortmund_electronic,
    sum_genre_dortmund_folkcountry / NULLIF(total_dortmund, 0) AS prop_genre_dortmund_folkcountry,
    sum_genre_dortmund_funksoulrnb / NULLIF(total_dortmund, 0) AS prop_genre_dortmund_funksoulrnb,
    sum_genre_dortmund_jazz / NULLIF(total_dortmund, 0) AS prop_genre_dortmund_jazz,
    sum_genre_dortmund_pop / NULLIF(total_dortmund, 0) AS prop_genre_dortmund_pop,
    sum_genre_dortmund_raphiphop / NULLIF(total_dortmund, 0) AS prop_genre_dortmund_raphiphop,
    sum_genre_dortmund_rock / NULLIF(total_dortmund, 0) AS prop_genre_dortmund_rock,
    -- Electronic proportions
    sum_genre_electronic_ambient / NULLIF(total_electronic, 0) AS prop_genre_electronic_ambient,
    sum_genre_electronic_dnb / NULLIF(total_electronic, 0) AS prop_genre_electronic_dnb,
    sum_genre_electronic_house / NULLIF(total_electronic, 0) AS prop_genre_electronic_house,
    sum_genre_electronic_techno / NULLIF(total_electronic, 0) AS prop_genre_electronic_techno,
    sum_genre_electronic_trance / NULLIF(total_electronic, 0) AS prop_genre_electronic_trance,
    -- Rosamerica proportions
    sum_genre_rosamerica_cla / NULLIF(total_rosamerica, 0) AS prop_genre_rosamerica_cla,
    sum_genre_rosamerica_dan / NULLIF(total_rosamerica, 0) AS prop_genre_rosamerica_dan,
    sum_genre_rosamerica_hip / NULLIF(total_rosamerica, 0) AS prop_genre_rosamerica_hip,
    sum_genre_rosamerica_jaz / NULLIF(total_rosamerica, 0) AS prop_genre_rosamerica_jaz,
    sum_genre_rosamerica_pop / NULLIF(total_rosamerica, 0) AS prop_genre_rosamerica_pop,
    sum_genre_rosamerica_rhy / NULLIF(total_rosamerica, 0) AS prop_genre_rosamerica_rhy,
    sum_genre_rosamerica_roc / NULLIF(total_rosamerica, 0) AS prop_genre_rosamerica_roc,
    sum_genre_rosamerica_spe / NULLIF(total_rosamerica, 0) AS prop_genre_rosamerica_spe,
    -- Tzanetakis proportions
    sum_genre_tzanetakis_blu / NULLIF(total_tzanetakis, 0) AS prop_genre_tzanetakis_blu,
    sum_genre_tzanetakis_cla / NULLIF(total_tzanetakis, 0) AS prop_genre_tzanetakis_cla,
    sum_genre_tzanetakis_cou / NULLIF(total_tzanetakis, 0) AS prop_genre_tzanetakis_cou,
    sum_genre_tzanetakis_dis / NULLIF(total_tzanetakis, 0) AS prop_genre_tzanetakis_dis,
    sum_genre_tzanetakis_hip / NULLIF(total_tzanetakis, 0) AS prop_genre_tzanetakis_hip,
    sum_genre_tzanetakis_jaz / NULLIF(total_tzanetakis, 0) AS prop_genre_tzanetakis_jaz,
    sum_genre_tzanetakis_met / NULLIF(total_tzanetakis, 0) AS prop_genre_tzanetakis_met,
    sum_genre_tzanetakis_pop / NULLIF(total_tzanetakis, 0) AS prop_genre_tzanetakis_pop,
    sum_genre_tzanetakis_reg / NULLIF(total_tzanetakis, 0) AS prop_genre_tzanetakis_reg,
    sum_genre_tzanetakis_roc / NULLIF(total_tzanetakis, 0) AS prop_genre_tzanetakis_roc
FROM genre_totals;