# admin-ui/Dockerfile
FROM nginx:1.27-alpine

# Copiamos los archivos estáticos
COPY . /usr/share/nginx/html

# Copiamos la configuración personalizada de Nginx
COPY ../nginx.conf /etc/nginx/nginx.conf
