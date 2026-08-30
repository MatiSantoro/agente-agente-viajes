# Agente-agente-viajes

Demo para la charla del AWS AI User Group Argentina (9 de septiembre de 2026): cómo construir un agente que consume cualquier API existente, sin implementar un servidor MCP ni escribir manualmente el ciclo de orquestación.

El proyecto integra Amazon Bedrock AgentCore de esta forma:

```text
Usuario autenticado
        |
        v
AgentCore Harness (modelo, instrucciones y Gateway ARN)
        |
        v
AgentCore Gateway (descubre y expone APIs como herramientas MCP)
        |
        v
TicketDesk API / Inventory API

AgentCore Identity aporta autorización OAuth delegada para que cada llamada se realice en nombre del usuario.
```

## Idea principal

El Harness sólo necesita conocer el ARN completo del Gateway. Por eso, cuando se incorpora una API nueva como target del Gateway, sus operaciones pasan a estar disponibles como herramientas MCP sin modificar ni redeplegar el agente. La demo muestra primero TicketDesk, ya conectado, y agrega Inventory en vivo para demostrar que el patrón es independiente de la API.

## Componentes

| Componente | Responsabilidad |
| --- | --- |
| **AgentCore Harness** | Declara y ejecuta el agente: modelo Bedrock, instrucciones y herramientas. |
| **AgentCore Gateway** | Conecta APIs REST existentes y las presenta al agente como herramientas MCP. |
| **AgentCore Identity** | Gestiona OAuth y autorización delegada, evitando credenciales estáticas en el agente. |
| **TicketDesk** | API de soporte que se usa como target inicial del Gateway. |
| **Inventory** | API de inventario que se agrega al Gateway durante la demo. |

## APIs de la demo

### TicketDesk

API REST interna para gestionar tickets de soporte:

- `GET /tickets` — listar tickets.
- `POST /tickets` — crear ticket (`title`, `description`).
- `GET /tickets/{id}` — obtener el detalle.
- `PATCH /tickets/{id}/status` — actualizar el estado.

### Inventory

API REST de inventario para probar que el enfoque es genérico:

- `GET /inventory` — listar productos y stock.
- `GET /inventory/{sku}` — obtener el detalle de un producto.
- `PATCH /inventory/{sku}/stock` — actualizar stock.

Ambas APIs se implementarán con AWS Lambda (Python) y Amazon API Gateway REST. Se validan con `curl` antes de conectarlas al Gateway.

## Flujo de la demo

1. Probar TicketDesk directamente con `curl`.
2. Invocar el agente del Harness para crear o consultar un ticket a través del Gateway.
3. Agregar Inventory como un nuevo target al Gateway desde la consola de AWS.
4. Iniciar una nueva invocación del agente y solicitar una operación de inventario, sin cambiar el Harness.
5. Mostrar los logs o trazas de Identity para comprobar que la API recibió la identidad del usuario, no una credencial fija ni la identidad del agente.

> Antes de la charla hay que verificar si una sesión ya iniciada descubre el target nuevo, o si hace falta iniciar una sesión nueva. El resultado debe documentarse aquí junto con el comando usado.

## Estructura prevista

```text
apis/
  ticketdesk/    # Lambda y definición/instrucciones de API Gateway
  inventory/     # Lambda y definición/instrucciones de API Gateway
gateway/         # Configuración y pasos para crear el Gateway y su target inicial
identity/        # Configuración del proveedor OAuth para autorización delegada
harness/         # Configuración del agente y comandos agentcore CLI
```

## Principios de seguridad

- No guardar claves de API ni credenciales estáticas en el agente.
- Usar AgentCore Identity con OAuth para autorización saliente delegada.
- Aplicar el mínimo privilegio a los roles de Lambda, Gateway y Harness.
- Registrar las invocaciones para vincular las llamadas a la identidad del usuario.

## Referencias

- [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/)
- [AgentCore samples de AWS Labs](https://github.com/awslabs/agentcore-samples)
- Serie de Vadym Kazulkin sobre AgentCore Gateway, Identity y Runtime en dev.to.

