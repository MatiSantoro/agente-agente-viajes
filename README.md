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
Flights API / Hotels API
```

AgentCore Identity aporta autorización OAuth delegada para que cada llamada se realice en nombre del usuario.

## Interfaz web de prueba

El proyecto incluirá una interfaz web pequeña para que las personas puedan probar el agente sin usar la terminal. La UI enviará los mensajes a un backend propio, y éste invocará AgentCore Harness; las credenciales y la configuración de AWS permanecerán siempre del lado servidor.

La interfaz deberá permitir:

- enviar una petición en lenguaje natural al agente;
- ver la respuesta y el estado de la invocación;
- iniciar una sesión nueva para validar que el agente descubra targets agregados recientemente al Gateway;
- mostrar ejemplos rápidos para vuelos y hoteles.

La UI será una herramienta de prueba para la demo, no reemplaza las invocaciones de CLI ni expone directamente las APIs o el ARN del Harness al navegador.

## Idea principal

El Harness sólo necesita conocer el ARN completo del Gateway. Por eso, cuando se incorpora una API nueva como target del Gateway, sus operaciones pasan a estar disponibles como herramientas MCP sin modificar ni redeplegar el agente. La demo muestra primero Flights, ya conectado, y agrega Hotels en vivo para demostrar que el patrón es independiente de la API. Finalmente, el agente combina ambas fuentes para proponer una alternativa de viaje que se ajuste a la solicitud del usuario.

## Componentes

| Componente | Responsabilidad |
| --- | --- |
| **AgentCore Harness** | Declara y ejecuta el agente: modelo Bedrock, instrucciones y herramientas. |
| **AgentCore Gateway** | Conecta APIs REST existentes y las presenta al agente como herramientas MCP. |
| **AgentCore Identity** | Gestiona OAuth y autorización delegada, evitando credenciales estáticas en el agente. |
| **Flights** | API de búsqueda de vuelos que se usa como target inicial del Gateway. |
| **Hotels** | API de búsqueda de hoteles que se agrega al Gateway durante la demo. |

## APIs de la demo

### Flights

API REST para buscar opciones de vuelo:

- `GET /flights` — buscar vuelos por origen, destino, fecha y cantidad de pasajeros.
- `GET /flights/{id}` — obtener el detalle de una opción de vuelo.

### Hotels

API REST para buscar alojamientos:

- `GET /hotels` — buscar hoteles por destino, fechas de entrada/salida y huéspedes.
- `GET /hotels/{id}` — obtener el detalle de una opción de alojamiento.

Ambas APIs se implementarán con AWS Lambda (Python) y Amazon API Gateway REST. Se validan con `curl` antes de conectarlas al Gateway. El agente usa los resultados de ambas para recomendar una combinación coherente de vuelo y hotel.

## Flujo de la demo

1. Probar Flights directamente con `curl`.
2. Invocar el agente del Harness para buscar un vuelo a través del Gateway.
3. Agregar Hotels como un nuevo target al Gateway desde la consola de AWS.
4. Iniciar una nueva invocación del agente y pedir una combinación de vuelo y hotel, sin cambiar el Harness.
5. Mostrar los logs o trazas de Identity para comprobar que la API recibió la identidad del usuario, no una credencial fija ni la identidad del agente.

> Antes de la charla hay que verificar si una sesión ya iniciada descubre el target nuevo, o si hace falta iniciar una sesión nueva. El resultado debe documentarse aquí junto con el comando usado.

## Estructura prevista

```text
apis/
  flights/       # Lambda y definición/instrucciones de API Gateway
  hotels/        # Lambda y definición/instrucciones de API Gateway
gateway/         # Configuración y pasos para crear el Gateway y su target inicial
identity/        # Configuración del proveedor OAuth para autorización delegada
harness/         # Configuración del agente y comandos agentcore CLI
web/             # UI de prueba y backend que invoca AgentCore Harness
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
