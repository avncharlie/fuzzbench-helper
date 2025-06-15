#!/usr/bin/env bash

# if script is backgrounded or so, ensure it ignores Ctrl-C itself
trap '' SIGINT

if [[ -z "$1" ]]; then
  echo "Usage: $0 <fuzzer-name>"
  exit 1
fi

fuzzer="$1"
benchmarks=(
  bloaty_fuzz_target
  curl_curl_fuzzer_http
  freetype2_ftfuzzer
  harfbuzz_hb-shape-fuzzer
  jsoncpp_jsoncpp_fuzzer
  lcms_cms_transform_fuzzer
  libjpeg-turbo_libjpeg_turbo_fuzzer
  libpcap_fuzz_both
  libpng_libpng_read_fuzzer
  libxml2_xml
  libxslt_xpath
  mbedtls_fuzz_dtlsclient
  mruby_mruby_fuzzer_8c8bbd
  openh264_decoder_fuzzer
  openssl_x509
  openthread_ot-ip6-send-fuzzer
  php_php-fuzz-parser_0dbedb
  proj4_proj_crs_to_crs_fuzzer
  re2_fuzzer
  sqlite3_ossfuzz
  stb_stbi_read_fuzzer
  systemd_fuzz-link-parser
  vorbis_decode_fuzzer
  woff2_convert_woff2ttf_fuzzer
  zlib_zlib_uncompress_fuzzer
)

for bench in "${benchmarks[@]}"; do
  clear
  cmd="make run-${fuzzer}-${bench}"
  echo "About to run: $cmd"
  read -p "[Enter to run, or 's' + Enter to skip] " choice

  if [[ "$choice" == "s" ]]; then
    echo "Skipped $bench."
  else
    echo "Running $cmd (press Ctrl-C to cancel)…"
    # run the command; on Ctrl-C this make dies, but our script keeps going
    $cmd
    # small pause so you see output if it exits quickly
    sleep 1
  fi
done

echo
echo "All done."
