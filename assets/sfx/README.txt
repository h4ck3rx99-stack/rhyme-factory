SOUND EFFECTS LIBRARY (one-time, free)
=====================================
The storyboard AI may only pick from these names. Put one WAV per name in this folder:

  sparkle.wav      (used automatically on title + ending)
  splash.wav       pop.wav          boing.wav        chime.wav
  whoosh.wav       giggle.wav       clap.wav         bell.wav
  footsteps.wav    bird_chirp.wav   rain_light.wav   wind_soft.wav
  car_horn_toy.wav train_toot.wav   animal_moo.wav   animal_quack.wav
  animal_roar_cute.wav  drum_roll.wav  ding.wav      snore.wav

Where to get them legally at Rs 0:
  * Freesound.org - filter "License: Creative Commons 0" (CC0 = no attribution, commercial OK).
    Keep a note of each sound's URL in sfx_sources.txt in case YouTube ever asks.
  * Or record them yourself (phone + Audacity), which is always safe.
Avoid "free" packs whose licence forbids redistribution inside videos, and anything CC-BY-NC.

Convert anything to WAV:   ffmpeg -i input.mp3 -ac 2 -ar 48000 splash.wav
Keep each effect short (0.3-2 s). Missing files are skipped, never fatal.

OPTIONAL channel sounds (folder ..\audio):
  jingle.wav     4-second channel signature played under the title card
  outro_bed.wav  6-second soft music under the goodbye card
Make both once with ACE-Step (instrumental) so they are yours.
