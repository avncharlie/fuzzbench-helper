#!/usr/bin/env bash

# ignore Ctrl-C in this wrapper so individual timeouts still work
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

# associative array to store PASS/FAIL
declare -A results

for bench in "${benchmarks[@]}"; do
  clear
  cmd="make test-run-${fuzzer}-${bench}"
  echo "Running: $cmd (timeout 5m)"
  
  # run under GNU timeout; exit status 124 = timeout
  timeout 300s $cmd
  exit_code=$?
  
  if [[ $exit_code -eq 0 ]]; then
    results[$bench]="PASS"
  else
    if [[ $exit_code -eq 124 ]]; then
      results[$bench]="FAIL (timeout)"
    else
      results[$bench]="FAIL (exit $exit_code)"
    fi
  fi
done

echo
echo "=== Benchmark Results for '$fuzzer' ==="
for bench in "${benchmarks[@]}"; do
  printf "%-40s %s\n" "$bench" "${results[$bench]}"
done
