# Reverse proxy and remote access

The sample Compose deployment binds FastAPI to `127.0.0.1`. Keep that default and terminate TLS on a host-managed reverse proxy. Do not expose PostgreSQL, Redis, Ollama, vLLM, or GROBID directly to the public network.

The following Nginx location is an illustrative starting point, not a complete TLS configuration. Supply certificates, modern TLS settings, access controls, and logs according to your institution's policy.

```nginx
# Place limit_req_zone in the nginx http {} context.
limit_req_zone $binary_remote_addr zone=argumentum_api:10m rate=5r/s;

server {
    listen 443 ssl;
    server_name research.example.edu;

    ssl_certificate     /etc/ssl/certs/research.example.edu.pem;
    ssl_certificate_key /etc/ssl/private/research.example.edu.key;

    client_max_body_size 105m;

    location / {
        limit_req zone=argumentum_api burst=20 nodelay;
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 5s;
        proxy_send_timeout 180s;
        proxy_read_timeout 180s;
        proxy_request_buffering on;
    }
}
```

The 105 MiB request ceiling allows multipart framing around the API's 100 MiB aggregate material limit. Align any upstream load balancer, WAF, and reverse-proxy limits with the application caps. Add stricter rate limits for expensive run submissions and upload requests as needed; the example applies one basic IP-based limit to all API routes.

For local-only use, do not install a reverse proxy or change the host binding. For remote access, use a firewall or VPN in addition to TLS. The API has tenant-scoped bearer credentials with owner/admin/researcher/viewer roles; it does not have browser password login or OIDC/SAML/SSO federation. A generic reverse proxy does not automatically map an external identity provider session to an Argumentum workspace credential. Keep the platform administrator token restricted to operators and use separate workspace credentials for researchers. PostgreSQL row-level security is not enabled; never expose the database directly to tenant users.
