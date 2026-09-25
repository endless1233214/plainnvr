#!/bin/sh
set -eu
# Retain camera transport, recording, audio conversion, snapshots and rotation.
# Do not ship unrelated subtitle/game codecs, device capture or XML/DASH stacks.
./configure --prefix="${FFMPEG_PREFIX:-/opt/ffmpeg}" \
  --disable-autodetect --disable-debug --disable-doc --disable-ffplay \
  --disable-everything --enable-network --enable-openssl --enable-version3 \
  --enable-protocol=file,pipe,rtp,tcp,udp,rtsp,http,https,tls,crypto \
  --enable-demuxer=rtsp,rtp,sdp,mov,mpegts,hls,mjpeg,aac,matroska \
  --enable-muxer=segment,mp4,rtsp,rtp,mpegts,image2pipe,rawvideo,null \
  --enable-decoder=h264,hevc,mjpeg,aac,aac_latm,pcm_alaw,pcm_mulaw,pcm_s16le,opus,vorbis,vp8,vp9,av1 \
  --enable-encoder=aac,mjpeg,pcm_s16le,rawvideo \
  --enable-parser=h264,hevc,aac,aac_latm,mjpeg,opus,vp8,vp9,av1 \
  --enable-filter=hue,scale,format,aresample,aformat,anull,null,transpose,rotate,fps,buffer,buffersink,abuffer,abuffersink \
  --enable-bsf=aac_adtstoasc,h264_mp4toannexb,hevc_mp4toannexb,extract_extradata
# Keep the reviewed attack-surface exclusions from silently reappearing.
for component in RASC_DECODER VOBSUB_DEMUXER SPDIF_MUXER ADPCM_ADX_DECODER \
  HQDN3D_FILTER CAF_DEMUXER PNG_DECODER SUP_DEMUXER PGSSUB_DECODER \
  WTV_DEMUXER DVBSUB_DECODER CFHD_DECODER DIRAC_DECODER DASH_DEMUXER \
  TDSC_DECODER DVDSUB_DECODER CONCAT_DEMUXER FLOODFILL_FILTER \
  SWAPRECT_FILTER IAMF_DEMUXER RSCC_DECODER SCREENPRESSO_DECODER TIFF_DECODER; do
  grep -q "#define CONFIG_${component} 0" config_components.h
done
make -j2
make install DESTDIR="${FFMPEG_DESTDIR:-}"
