# Diagramas de Arquitetura SIVIT

## Arquitetura de Software (Padrão MVT do Django)
O diagrama seguinte ilustra a estrutura interna da aplicação Django, baseada no padrão Model-View-Template.

```mermaid
graph TD
    Client[Browser] -->|HTTP Request| URL[urls.py]
    URL -->|Routing| View[views.py - dashboard]
    View -->|Query Dados| Models[models.py]
    Models -->|Retorna| View
    View -->|Contexto| Template[dashboard.html]
    Template -->|Renderiza HTML| View
    View -->|HTTP Response| Client

    subgraph "Camada de Dados (Models)"
        Patient
        Admission
        Device
        Reading
    end
    Models -.-> Patient
    Models -.-> Admission

graph LR
    Browser[Cliente Web] -->|Porta 80| Nginx[Contentor: web <br> Nginx]
    
    subgraph "Docker Host"
        Nginx -->|Reverse Proxy| Gunicorn[Contentor: portal <br> Gunicorn + Django]
        Nginx -.->|Volume| Static[Volume: static_volume <br> /var/www/static]
        Gunicorn -.->|Volume| Static
        Gunicorn -->|Porta 5432| DB[Contentor: sivitDB <br> PostgreSQL 16]
        DB -.->|Persistência| DBVol[Volume: db_data]
    end