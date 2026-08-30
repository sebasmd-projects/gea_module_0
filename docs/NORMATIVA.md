# Encaje normativo de la certificación AEGIS

> Decisión registrada el 30 de agosto de 2026. Informe completo, con fuentes por
> jurisdicción: <https://claude.ai/code/artifact/7f9e0ecb-ece3-4ce5-b7ef-306e541f6c90>

## La decisión

**No se adopta W3C Verifiable Credentials.** Ninguna entidad reguladora,
certificadora, bancaria ni financiera de Colombia, Estados Unidos, Europa o Asia
la exige hoy para acreditar la integridad de un documento, y adoptarla no
cambiaría el valor probatorio de ningún certificado ya emitido.

El motivo es que resuelve otro problema. Hay dos carriles que se confunden:

| | Acredita | Estándares | ¿AEGIS? |
|---|---|---|---|
| **A. Identidad** | Atributos de un sujeto: quién es, qué título tiene | W3C VC 2.0, eIDAS 2 / cartera EUDI | No |
| **B. Integridad y tiempo** | Que un archivo no ha cambiado desde una fecha | RFC 3161, eIDAS arts. 41–42, Ley 527/1999, FRE 902(13)-(14) | **Sí** |

Las carteras EUDI usan credenciales W3C, y de ahí viene la impresión de que el
estándar se vuelve obligatorio: lo que los Estados miembros deben ofrecer a
finales de 2026 son carteras **de identidad**, que no alcanzan a un certificado
de integridad documental.

## Lo que sí falta, por impacto

1. **Apuntar `CERTIFICATION_TSA_URL` a una autoridad acreditada** (Certicámara
   para ONAC, o un QTSP de la lista eIDAS). Una TSA gratuita es criptográficamente
   idéntica y jurídicamente no: es la diferencia entre un indicio y una presunción
   legal. El token se guarda tal cual, así que cambiar de proveedor no invalida
   los ya emitidos. Es la acción de mayor impacto de toda la lista.
2. **Verificar que en producción hay `CERTIFICATION_SIGNING_KEY`.** Sin ella el
   registro se sella con HMAC y solo la propia plataforma puede verificarlo, que
   es justo lo contrario de para lo que existe.
3. **Declaración de persona cualificada** sobre el registro: es lo que lo hace
   autoautenticable bajo FRE 902(14) en EEUU. El contenido ya se produce; falta
   el envoltorio con nombre, cargo y firma.
4. **Política de conservación y revocación.** El modelo ya tiene `VALID`,
   `EXPIRED` y `REVOKED`; falta el documento que diga quién los cambia y con qué
   criterio.

## Si algún día se adopta VC

La criptosuite `eddsa-jcs-2022` usa exactamente lo que ya hay: canonicalización
JCS (RFC 8785) más firma Ed25519. El mapeo desde el registro actual es casi campo
a campo (`issuer`, `validFrom`, `credentialSubject`, `credentialStatus`, `proof`).

**Cautela:** el registro se firma sobre sus bytes exactos y el master hash de las
cajas depende de `services/jcs.py`. Reestructurar campos para parecerse a VC
**invalidaría todas las huellas ya emitidas** (invariantes 10 y 17 de CLAUDE.md).
La vía sería emitir la VC como representación **adicional**, nunca sustituir el
registro.

## Cuándo reabrir la decisión

- Si una contraparte concreta lo pide por escrito. Ese es el disparador real.
- Si la plataforma pasa a acreditar atributos de personas (que un tenedor es quien
  dice ser). Eso sí es el carril A, y ahí VC es el estándar correcto.
- Si se quiere entrar en una cartera EUDI, lo que exige además ser proveedor de
  servicios de confianza, no solo el formato.

> Esto es análisis de encaje técnico-normativo para priorizar ingeniería, no
> asesoría jurídica. Contrastar con el asesor legal de cada jurisdicción antes de
> comprometer nada frente a una entidad concreta.
