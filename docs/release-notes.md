## CoraNotes — versión portable para Windows 10/11 (64 bits)

No hace falta instalar nada: el zip trae Python 3.13 (paquete oficial de python.org, verificado por SHA-256 y firma)
y todas las librerías.

### Probar la demo (3 minutos, sin internet ni clave de Gemini)

1. Descargá `CoraNotes-<versión>-windows-x64.zip` (abajo, en *Assets*).
2. Clic derecho sobre el zip → **Propiedades** → marcá **Desbloquear** → Aceptar. Descomprimilo (por ejemplo en Documentos).
3. Doble clic en **`Demo CoraNotes.bat`**. Se abre el navegador y aparece **Cora** en el escritorio.
4. En la página de Inicio presioná **Cargar datos ficticios**: a los 2 minutos Cora pide comida, a los 6 se prepara
   el prompt semanal para Claude.
5. Hacé clic en el globo de Cora, guardá una actividad y mirá cómo come.

Si Windows muestra «Windows protegió su PC» al abrir un `.bat`: **Más información → Ejecutar de todas formas**
(los scripts no están firmados digitalmente).

Para detener: `Detener Demo.bat`. Para empezar la demo de cero: `Reiniciar Demo.bat`.

Verificación del archivo: el `.sha256` adjunto contiene el hash del zip.
