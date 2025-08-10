#!/bin/bash

if [[ "$#" -ne 2 ]]; then
    echo "Usage: add.sh <library_name> <library_version>"
    exit 1
fi

library_name=$1
library_version=$2

fetch_url="https://github.com/dejwk/${library_name}/archive/refs/tags/${library_version}.zip"

mkdir tmp
cd tmp
wget $fetch_url
if [ $? -ne 0 ]; then
    echo "Error: Failed to fetch the repo"
    exit 1
fi
unzip ${library_version}.zip

if [ ! -e "${library_name}-${library_version}/MODULE.bazel" ]; then
    echo "Error: not a Bazel module."
    cd ..
    rm -rf tmp
    exit 1
fi

integrity=`openssl dgst -binary ${library_version}.zip | openssl base64 -A`

cd ..

mkdir modules/${library_name}
mkdir modules/${library_name}/${library_version}
cp tmp/${library_name}-${library_version}/MODULE.bazel modules/${library_name}/${library_version}

/bin/cat <<EOM > modules/${library_name}/${library_version}/source.json
{
    "url": "${fetch_url}",
    "integrity": "sha256-${integrity}",
    "strip_prefix": "${library_name}-${library_version}"
}
EOM

git add modules/${library_name}/${library_version}
git add modules/${library_name}/${library_version}/source.json
git commit -m "Added ${library_name} ${library_version} to the registry."

rm -rf tmp
