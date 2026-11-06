# PDF a EPUB

Aplicación local para Windows que convierte libros PDF en EPUB de texto adaptable.

## Instalación

1. Instalá Python 3.12 con su lanzador para Windows.
2. Descargá o cloná este repositorio.
3. Ejecutá **Instalar.cmd** una vez para preparar las dependencias.
4. Abrí **Abrir herramienta.cmd**.

La interfaz se abre en el navegador. Arrastrá uno o varios PDF y pulsá **Convertir a EPUB**. Los resultados se guardan en **epub**; el botón **Abrir carpeta de salida** permite encontrarlos.

El OCR (reconocimiento óptico de caracteres) usa las funciones integradas en Windows. Los idiomas se comparan automáticamente entre los que estén instalados. Podés agregar funciones de reconocimiento desde la configuración de idiomas de Windows. El texto existente se aprovecha para evitar repetir el reconocimiento de todo el libro.

## Funciones

- Texto adaptable, eliminación de encabezados y folios repetidos.
- Índice interactivo a partir del índice original o de los títulos de las secciones.
- Notas separadas del cuerpo, con enlaces desde las referencias reconocidas.
- Tablas y fórmulas complejas conservadas como imágenes del original.
- Sugerencias de corrección con diccionarios de español e inglés y vocabulario ampliable.
- Revisión junto a un recorte del PDF original y botón **Corregir todo** para aplicar las sugerencias de una vez.
- Comprobación del EPUB y sus enlaces antes de reemplazar un resultado anterior.

Los libros se procesan en el equipo. La conversión no envía sus archivos a servicios externos ni descarga modelos de lenguaje. La detección de tablas, fórmulas, estructura y errores OCR puede fallar: conviene revisar el resultado, especialmente en documentos científicos o con diseños complejos.

Hay más detalles de funcionamiento y limitaciones en [LEEME.md](LEEME.md).

## Línea de comandos

```powershell
.venv\Scripts\python.exe internos\convertir.py "libro.pdf" --salida epub
.venv\Scripts\python.exe internos\convertir.py --validar "epub\libro.epub"
```

## Pruebas

Las pruebas unitarias se ejecutan sin libros externos:

```powershell
.venv\Scripts\python.exe internos\run_tests.py
```

Las pruebas adicionales sobre páginas de libros originales no distribuidos se ejecutan con `--fuentes`. Colocá las muestras en `tests/samples` o indicá otra carpeta con la variable `PDF_EPUB_SAMPLE_DIR`. Los nombres y páginas utilizados están descritos en `internos/test_source_samples.py`. Los PDF y EPUB no forman parte del repositorio.

## Componentes incluidos

Los diccionarios conservan sus licencias y avisos originales. Ver [THIRD_PARTY.md](THIRD_PARTY.md). Las dependencias de Python se instalan a partir de `internos/requirements.txt`.
