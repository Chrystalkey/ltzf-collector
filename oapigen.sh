export OPENAPI_GENERATOR_VERSION="7.13.0"
DIRECTORY="oapi-generator"

echo "Checking for openapi-generator-cli"

if [ -d "$DIRECTORY" ]; then
    echo "Directory $DIRECTORY found!"
else
    echo "Creating $DIRECTORY directory"
    mkdir "$DIRECTORY"
    cd "$DIRECTORY"
    curl https://raw.githubusercontent.com/OpenAPITools/openapi-generator/master/bin/utils/openapi-generator-cli.sh > openapi-generator-cli
    chmod u+x openapi-generator-cli
    curl raw.githubusercontent.com/Chrystalkey/landtagszusammenfasser/refs/heads/dev-specchange/docs/specs/openapi.yml > openapi.yml
    cd ..
fi

./$DIRECTORY/openapi-generator-cli generate -g python -i $DIRECTORY/openapi.yml -o $(pwd)/oapicode