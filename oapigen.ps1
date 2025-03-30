echo "Checking for openapi-generator-cli"

if (-Not (Test-Path -Path "oapi-generator" -PathType Container)) {
    Write-Host "Creating oapi-generator directory"
    New-Item -ItemType Directory -Path "oapi-generator" -Force | Out-Null
    Set-Location -Path "oapi-generator"
    
    # Download the openapi-generator-cli script
    & Invoke-WebRequest -OutFile openapi-generator-cli.jar https://repo1.maven.org/maven2/org/openapitools/openapi-generator-cli/7.11.0/openapi-generator-cli-7.11.0.jar
    & Invoke-WebRequest -OutFile openapi.yml https://raw.githubusercontent.com/Chrystalkey/landtagszusammenfasser/refs/heads/main/docs/specs/openapi.yml
    Set-Location -Path ".."
}


& java -jar "./oapi-generator/openapi-generator-cli.jar" generate -g rust-axum -i "$(Get-Location)/oapi-generator/openapi.yml" -o "$(Get-Location)/oapicode"