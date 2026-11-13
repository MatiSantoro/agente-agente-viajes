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
Flights API / Hotels API / Locations API
```

AgentCore Identity aporta autorización OAuth delegada para que cada llamada se realice en nombre del usuario.

## Interfaz web de prueba

El proyecto incluye una interfaz web pequeña para que las personas puedan probar el agente sin usar la terminal. La UI envía los mensajes a un backend propio, y éste invoca AgentCore Harness; las credenciales y la configuración de AWS permanecen siempre del lado servidor.

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
| **Locations** | API de resolución de ciudades y aeropuertos que permanece conectada desde el inicio. |

## APIs de la demo

### Flights

API REST para buscar opciones de vuelo:

- `GET /flights` — buscar vuelos por origen, destino, fecha y cantidad de pasajeros; devuelve capacidad y plazas disponibles.
- `GET /flights/{id}` — obtener el detalle de una opción de vuelo.
- `GET /flights/availability` — descubrir fechas disponibles para una ruta y cantidad de pasajeros.

### Hotels

API REST para buscar alojamientos:

- `GET /hotels` — buscar hoteles por destino, fechas de entrada/salida y huéspedes; una habitación con capacidad mayor también es válida.
- `GET /hotels/{id}` — obtener el detalle de una opción de alojamiento.
- `GET /hotels/availability` — descubrir estadías por capacidad de habitación y cantidad de huéspedes.

Las APIs se implementan con AWS Lambda (Python) y Amazon API Gateway REST. Se validan con `curl` antes de conectarlas al Gateway. El agente usa Locations para resolver códigos y combina los resultados de Flights y Hotels para recomendar una alternativa coherente.

### Locations

API REST para resolver nombres de ciudades o aeropuertos antes de consultar disponibilidad:

- `GET /locations` — recibe `query` y devuelve códigos de ubicación y aeropuertos utilizables, por ejemplo `Buenos Aires` → `EZE` y `AEP`.

Locations se conecta desde el inicio junto con Flights. Hotels queda desplegado como backend con datos para diciembre y fechas cercanas, pero su integración OAuth y target se configuran en vivo.

## Flujo de la demo

1. Probar Flights directamente con `curl`.
2. Invocar el agente del Harness para buscar un vuelo a través del Gateway.
3. Crear en vivo los componentes OAuth de Hotels, proteger sus métodos y agregar Hotels como REST API target desde la consola de AWS.
4. Iniciar una nueva invocación del agente y pedir una combinación de vuelo y hotel, sin cambiar el Harness.
5. Mostrar los logs o trazas de Identity para comprobar que la API recibió la identidad del usuario, no una credencial fija ni la identidad del agente.

El OpenAPI inline exacto para Hotels se obtiene después del despliegue con:

```bash
.venv/bin/python Scripts/17_print_hotels_openapi.py
```

> Antes de la charla hay que verificar si una sesión ya iniciada descubre el target nuevo, o si hace falta iniciar una sesión nueva. El resultado debe documentarse aquí junto con el comando usado.

## Despliegue reproducible

El repositorio tiene un único punto de entrada para desplegar la demo completa. Los módulos siguen separados para que cada parte sea revisable, pero no hace falta ejecutar una lista manual de comandos:

```bash
.venv/bin/python -m pip install -r Scripts/requirements.txt
.venv/bin/python Scripts/00_deploy.py
```

Ese comando crea las tres APIs proveedoras, sus tablas DynamoDB con inventario de demostración, Lambdas, roles IAM, los dos User Pools, AgentCore Gateway, Identity, Harness y la UI. El despliegue inicial deja Hotels como backend existente, pero sin su app client OAuth, Identity provider, authorizer, permisos del Gateway ni target. Esos pasos se hacen manualmente en la consola durante la demo. Los IDs generados por AWS no están hardcodeados: se descubren por nombre y se guardan solamente en `Scripts/.state.json`, que no se versiona.

## Estructura

```text
Scripts/
  00_deploy.py   # único entrypoint de provisioning
  07_provider_apis.py # tablas, datos, Lambdas y APIs REST
  01–16_*.py     # módulos idempotentes de Cognito, Gateway, Identity, Harness y UI
UI/              # UI de prueba publicada en S3/CloudFront
lambda/          # Handlers de Flights, Hotels, Locations y chat
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
