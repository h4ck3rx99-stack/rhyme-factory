# Texts to paste into YouTube Studio and Google Cloud

## Channel
- Name: Puddlehop Lane
- Handle: @PuddlehopLane (if taken: @PuddlehopLaneSongs, then @PuddlehopLaneKids)
- Studio > Settings > Channel > Advanced settings > Audience: "Yes, set this channel as made for kids"
- Studio > Settings > Channel > Basic info > Country: India
- Studio > Settings > Upload defaults: Visibility Private; Category Education; Video language English;
  Caption certification "This content has never aired on television in the U.S."

Keywords (Settings > Channel > Basic info):

    puddlehop lane, nursery rhymes, kids songs, songs for toddlers, preschool songs, sing along songs, learning songs, counting songs, animal songs, original nursery rhymes

Description (Customization > Profile > Description):

    Welcome to Puddlehop Lane! Pip the duckling and friends sing brand-new, original songs for toddlers and preschoolers (ages 2-6). Every song teaches something small and real - counting, colours, animal sounds, kind words, bath time, bedtime - with a gentle story, simple words and a chorus little ones can sing after one listen.

    New songs every Monday, Wednesday and Friday.

    Our songs, lyrics and characters are original. We make them with the help of AI tools and check every video for safety and quality before it is published.

    For grown-ups: sing along, copy the actions, and pause to count or name things together.

## The 11 playlists (Studio > Create > New playlist, Public; titles must match exactly)

| Title | Description |
| --- | --- |
| Animal Songs on Puddlehop Lane | Sing along with Pip, Momo, Bix, Tula and their animal friends. Original animal songs with sounds, actions and simple facts for toddlers and preschoolers. |
| Counting Songs for Kids | Count to 10 and back again with Pip and friends. Original counting songs that make numbers easy and fun for little ones. |
| Colors, Shapes & Opposites | Red and blue, circles and squares, big and small, up and down. Original learning songs about colours, shapes, sizes and opposites. |
| Bath, Bedtime & Routine Songs | Songs for brushing teeth, bath time, tidying up, getting dressed and going to sleep. Gentle, original routine songs for toddlers. |
| Feelings & Friendship Songs | Sharing, saying sorry, feeling happy, sad or brave, and being a good friend. Original songs about feelings and kindness. |
| Nature, Weather & Seasons | Rain, sun, wind, flowers, bugs and the garden. Original songs about nature and weather on Puddlehop Lane. |
| Things That Go | Cars, trains, buses, boats and more. Original vehicle songs with fun sounds for toddlers. |
| Yummy Food Songs | Fruits, vegetables and healthy snacks. Original food songs that make trying new foods fun. |
| ABC & First Words | Letters, sounds and first words. Original alphabet and early-language songs for preschoolers. |
| Move & Dance Songs | Clap, stomp, wiggle and dance. Original action and instrument songs to get little ones moving. |
| Adventure Songs | Trips to the stars, the moon and under the sea. Original adventure songs about space and ocean animals. |

Copy each playlist's link (youtube.com > your channel > Playlists > open it > address bar) into
`n8n\my_settings.json` next to its exact title.

## Google Cloud OAuth scopes (Data access > Add or remove scopes > Manually add scopes)

    https://www.googleapis.com/auth/youtube.upload
    https://www.googleapis.com/auth/youtube
    https://www.googleapis.com/auth/youtube.readonly
    https://www.googleapis.com/auth/yt-analytics.readonly
    https://www.googleapis.com/auth/spreadsheets
    https://www.googleapis.com/auth/drive.file

Redirect URI for the Web OAuth client: `http://localhost:5678/rest/oauth2-credential/callback`
