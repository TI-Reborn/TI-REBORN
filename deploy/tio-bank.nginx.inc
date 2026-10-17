# Include inside the EXISTING TLS portal server block; preserve its certificate,
# downloads, updates and ACME locations. These are Next routes, not the private
# gateway. Never forward /v1/bank or port 8082 to the internet.
location = /api/bank/stripe/webhook {
    client_max_body_size 256k;
    proxy_pass http://127.0.0.1:3000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 5s;
    proxy_read_timeout 30s;
    proxy_request_buffering on;
    access_log off;
}
location ^~ /api/bank/ {
    client_max_body_size 4k;
    proxy_pass http://127.0.0.1:3000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 5s;
    proxy_read_timeout 30s;
    access_log off;
}
