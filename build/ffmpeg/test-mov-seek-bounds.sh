#!/bin/sh
set -eu
# Compile the real patched function with a minimal model of its context. ASan
# makes the unequal-length array regression observable, not just a text check.
cat > /tmp/mov-bounds.c <<'C'
#include <stdint.h>
#include <stdlib.h>
#include <assert.h>
#define AV_CODEC_ID_HEVC 173
#define av_assert0 assert
typedef struct { int64_t timestamp; } AVIndexEntry;
typedef struct { AVIndexEntry *index_entries; int nb_index_entries; } FFStream;
typedef struct { int codec_id; } AVCodecParameters;
typedef struct { int sample_offsets_count; int64_t *sample_offsets; int64_t dts_shift; } MOVStreamContext;
typedef struct { void *priv_data; AVCodecParameters *codecpar; FFStream *internal; } AVStream;
static FFStream *ffstream(AVStream *st) { return st->internal; }
static int is_open_key_sample(MOVStreamContext *sc, int sample) { return 0; }
C
awk '/^static int can_seek_to_key_sample\(/ { capture=1 } capture { print } capture && /^}/ { exit }' libavformat/mov.c >> /tmp/mov-bounds.c
cat >> /tmp/mov-bounds.c <<'C'
int main(void) {
  AVIndexEntry *entries = calloc(1, sizeof(*entries));
  int64_t *offsets = calloc(2, sizeof(*offsets));
  FFStream internal = { entries, 1 };
  MOVStreamContext mov = { 2, offsets, 0 };
  AVCodecParameters codec = { AV_CODEC_ID_HEVC };
  AVStream stream = { &mov, &codec, &internal };
  assert(can_seek_to_key_sample(&stream, -1, 0) == 1);
  assert(can_seek_to_key_sample(&stream, 1, 0) == 1);
  assert(can_seek_to_key_sample(&stream, 2, 0) == 1);
  assert(can_seek_to_key_sample(&stream, 0, 0) == 1);
  free(entries); free(offsets);
  return 0;
}
C
cc -fsanitize=address,undefined -g /tmp/mov-bounds.c -o /tmp/mov-bounds
/tmp/mov-bounds
