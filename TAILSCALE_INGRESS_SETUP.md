# Tailscale Ingress Setup for Claude Code

## Overview

The `main.py` file has been updated to automatically create Tailscale ingresses and services when a `claud-code` CRD is created. This eliminates the need for static YAML files and provides a fully programmatic approach.

## What Gets Created

When a `claud-code` CRD is created, the following resources are automatically created:

### Services
1. **Main Service** (`{metadata_name}-service`)
   - Exposes port 8080 (code-server)
   - Exposes port 8081 (http)
   - Selector: `app: {metadata_name}`

2. **Nginx Service** (`{metadata_name}-nginx-service`)
   - Exposes port 80 (nginx)
   - Selector: `app: {metadata_name}-nginx`

### Tailscale Ingresses
1. **Code Server Ingress** (`{metadata_name}-code-server-ingress`)
   - Exposes code-server on port 8080
   - Host: `{metadata_name}-code-server`
   - Backend: Main service port 8080

2. **HTTP Ingress** (`{metadata_name}-http-ingress`)
   - Exposes HTTP service on port 8081
   - Host: `{metadata_name}-http`
   - Backend: Main service port 8081

3. **Nginx Ingress** (`{metadata_name}-nginx-ingress`)
   - Exposes nginx on port 80
   - Host: `{metadata_name}-nginx`
   - Backend: Nginx service port 80

## Configuration

All ingresses include:
- `tailscale.com/expose: "true"` annotation
- `ingressClassName: tailscale`
- TLS configuration with appropriate hostnames
- Default backend pointing to the correct service and port

## Cleanup

When a `claud-code` CRD is deleted, all associated resources are automatically cleaned up:
- Services (main and nginx)
- Ingresses (code-server, http, and nginx)
- Deployments
- ConfigMaps
- PVCs
- RBAC resources

## RBAC Permissions

The operator now has the necessary permissions to:
- Create, update, and delete services
- Create, update, and delete ingresses
- Manage all other resources (deployments, PVCs, etc.)

## Usage

Simply create a `claud-code` CRD and the operator will automatically:
1. Create the namespace (if it doesn't exist)
2. Set up RBAC resources
3. Create PVCs for data and metadata
4. Deploy the main application with code-server and HTTP containers
5. Deploy nginx for serving static files
6. Create services to expose the deployments
7. Create Tailscale ingresses to expose the services externally

The services will be accessible via Tailscale at:
- `https://{metadata_name}-code-server` (code-server on port 8080)
- `https://{metadata_name}-http` (HTTP service on port 8081)
- `https://{metadata_name}-nginx` (nginx on port 80) 