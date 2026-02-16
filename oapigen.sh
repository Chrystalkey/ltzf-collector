#!/bin/bash

OPENAPI_GENERATOR_VERSION="7.15.0"
DIRECTORY="oapi-generator"
SPEC_PATH="https://raw.githubusercontent.com/Chrystalkey/landtagszusammenfasser/9c20dd1913eac99bd14edcd9676e188305064f1a/docs/specs/openapi.yml"

echo "Checking for openapi-generator-cli"

# Create oapi-generator directory if it doesn't exist
if [ ! -d $DIRECTORY ]; then
    echo "Creating oapi-generator directory"
    mkdir $DIRECTORY
    cd $DIRECTORY || exit

    curl -o openapi-generator-cli.jar https://repo1.maven.org/maven2/org/openapitools/openapi-generator-cli/$OPENAPI_GENERATOR_VERSION/openapi-generator-cli-$OPENAPI_GENERATOR_VERSION.jar
    curl -o openapi.yml $SPEC_PATH

    cd ..
fi

# Download JAR if missing
if [ ! -f "$DIRECTORY/openapi-generator-cli.jar" ]; then
    echo "Downloading OApi Generator"
    cd $DIRECTORY || exit
    curl -o openapi-generator-cli.jar https://repo1.maven.org/maven2/org/openapitools/openapi-generator-cli/$OPENAPI_GENERATOR_VERSION/openapi-generator-cli-$OPENAPI_GENERATOR_VERSION.jar
    cd ..
fi

# Download YAML spec if missing
if [ ! -f "oapi-generator/openapi.yml" ]; then
    echo "Downloading OApi Spec"
    cd $DIRECTORY || exit
    curl -o openapi.yml $SPEC_PATH
    cd ..
fi

java -jar ./$DIRECTORY/openapi-generator-cli.jar generate -g python -i $DIRECTORY/openapi.yml -o $(pwd)/oapicode
