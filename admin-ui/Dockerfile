# admin-ui/Dockerfile

FROM nginx:1.27-alpine

# Declara el arg (valor por defecto: nginx.conf en el contexto)
ARG NGINX_FILE_PATH=nginx.conf

# mete todo el admin-ui en /usr/share/nginx/html
COPY . /usr/share/nginx/html

# copia la configuración parametrizada
COPY ${NGINX_FILE_PATH} /etc/nginx/nginx.conf
