echo "Checking for openapi-generator-cli"
$VERSION="7.14.0"

if (-Not (Test-Path -Path "oapi-generator" -PathType Container)) {
    Write-Host "Creating oapi-generator directory"
    New-Item -ItemType Directory -Path "oapi-generator" -Force | Out-Null
    Set-Location -Path "oapi-generator"
    
    & Invoke-WebRequest -OutFile openapi-generator-cli.jar https://repo1.maven.org/maven2/org/openapitools/openapi-generator-cli/$VERSION/openapi-generator-cli-$VERSION.jar
    & Invoke-WebRequest -OutFile openapi.yml raw.githubusercontent.com/Chrystalkey/landtagszusammenfasser/refs/heads/dev-specchange/docs/specs/openapi.yml
    Set-Location -Path ".."
}
if (-Not (Test-Path -Path "oapi-generator/openapi-generator-cli.jar" -PathType Leaf)) {
    Write-Host "Downloading OApi Generator"
    Set-Location -Path "oapi-generator"
    & Invoke-WebRequest -OutFile openapi-generator-cli.jar https://repo1.maven.org/maven2/org/openapitools/openapi-generator-cli/$VERSION/openapi-generator-cli-$VERSION.jar
    Set-Location -Path ".."
}
if (-Not (Test-Path -Path "oapi-generator/openapi.yml" -PathType Leaf)) {
    Write-Host "Downloading OApi Spec"
    Set-Location -Path "oapi-generator"
    & Invoke-WebRequest -OutFile openapi.yml raw.githubusercontent.com/Chrystalkey/landtagszusammenfasser/refs/heads/dev-specchange/docs/specs/openapi.yml
    Set-Location -Path ".."
}


& java -jar "./oapi-generator/openapi-generator-cli.jar" generate -g python -i "$(Get-Location)/oapi-generator/openapi.yml" -o "$(Get-Location)/oapicode"