package com.example.filepreview.service;

import com.example.filepreview.model.FileInfo;
import com.example.filepreview.model.FilePreviewResponse;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.poi.hslf.usermodel.HSLFPictureData;
import org.apache.poi.hslf.usermodel.HSLFPictureShape;
import org.apache.poi.hslf.usermodel.HSLFShape;
import org.apache.poi.hslf.usermodel.HSLFSlide;
import org.apache.poi.hslf.usermodel.HSLFSlideShow;
import org.apache.poi.hslf.usermodel.HSLFTextShape;
import org.apache.poi.hssf.usermodel.HSSFWorkbook;
import org.apache.poi.hwpf.HWPFDocument;
import org.apache.poi.hwpf.extractor.WordExtractor;
import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.DataFormatter;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.xslf.usermodel.XMLSlideShow;
import org.apache.poi.xslf.usermodel.XSLFPictureData;
import org.apache.poi.xslf.usermodel.XSLFPictureShape;
import org.apache.poi.xslf.usermodel.XSLFShape;
import org.apache.poi.xslf.usermodel.XSLFSlide;
import org.apache.poi.xslf.usermodel.XSLFTextShape;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.apache.poi.xwpf.usermodel.BodyElementType;
import org.apache.poi.xwpf.usermodel.IBodyElement;
import org.apache.poi.xwpf.usermodel.XWPFDocument;
import org.apache.poi.xwpf.usermodel.XWPFParagraph;
import org.apache.poi.xwpf.usermodel.XWPFPicture;
import org.apache.poi.xwpf.usermodel.XWPFPictureData;
import org.apache.poi.xwpf.usermodel.XWPFRun;
import org.apache.poi.xwpf.usermodel.XWPFTable;
import org.apache.poi.xwpf.usermodel.XWPFTableCell;
import org.apache.poi.xwpf.usermodel.XWPFTableRow;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Comparator;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.stream.Collectors;
import java.util.stream.Stream;

@Service
public class FileService {

    private static final String UPLOAD_DIR = "uploads";
    private static final String INDEX_FILE = "file-index.json";

    private static final Set<String> PREVIEWABLE_SUFFIX = Set.of(
            "txt", "md", "json", "xml", "csv", "log",
            "java", "js", "ts", "vue", "html", "css",
            "sql", "py", "yml", "yaml", "properties",
            "doc", "docx", "xls", "xlsx", "ppt", "pptx", "pdf"
    );

    private static final Set<String> DIRECT_EDITABLE_SUFFIX = Set.of(
            "txt", "md", "json", "xml", "csv", "log",
            "java", "js", "ts", "vue", "html", "htm", "css",
            "sql", "py", "yml", "yaml", "properties"
    );

    private static final int MAX_PREVIEW_LINES = 500;
    private static final int MAX_PREVIEW_CHARS = 50000;
    private static final int MAX_HTML_CHARS = 8_000_000;
    private static final int MAX_EMBED_IMAGES = 120;
    private static final int MAX_IMAGE_BYTES = 8 * 1024 * 1024;

    private final Map<Long, FileInfo> fileStore = new ConcurrentHashMap<>();
    private final AtomicLong idGenerator = new AtomicLong(1);
    private final ObjectMapper objectMapper = new ObjectMapper();
    private final SimpleDateFormat dateFormat = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss");

    public FileService() throws IOException {
        Path uploadPath = Paths.get(UPLOAD_DIR);
        if (!Files.exists(uploadPath)) {
            Files.createDirectories(uploadPath);
        }
        loadFileStore(uploadPath);
    }

    public FileInfo upload(MultipartFile file) throws IOException {
        if (file == null || file.isEmpty()) {
            throw new RuntimeException("上传文件不能为空");
        }

        String originalFilename = file.getOriginalFilename();
        String suffix = getSuffix(originalFilename);

        String storedName = UUID.randomUUID() + "_" + originalFilename;
        Path targetPath = Paths.get(UPLOAD_DIR, storedName);

        Files.copy(file.getInputStream(), targetPath, StandardCopyOption.REPLACE_EXISTING);

        Long id = idGenerator.getAndIncrement();
        FileInfo fileInfo = new FileInfo(
                id,
                originalFilename,
                targetPath.toAbsolutePath().toString(),
                suffix,
                file.getSize(),
                dateFormat.format(new Date())
        );

        fileStore.put(id, fileInfo);
        persistFileStore();
        return fileInfo;
    }

    public List<FileInfo> list() {
        List<FileInfo> list = new ArrayList<>(fileStore.values());
        list.sort(Comparator.comparing(FileInfo::getId).reversed());
        return list;
    }

    public FilePreviewResponse preview(Long id) throws IOException {
        FileInfo fileInfo = fileStore.get(id);
        if (fileInfo == null) {
            throw new RuntimeException("文件不存在");
        }

        String suffix = fileInfo.getSuffix().toLowerCase();
        if (!PREVIEWABLE_SUFFIX.contains(suffix)) {
            return new FilePreviewResponse(
                    fileInfo.getFileName(),
                    "text",
                    "当前文件类型暂不支持文本预览",
                    false
            );
        }

        PreviewReadResult readResult;
        String previewType = "text";

        switch (suffix) {
            case "doc" -> readResult = readDocFile(fileInfo.getFilePath());
            case "docx" -> {
                readResult = readDocxAsHtml(fileInfo.getFilePath());
                previewType = "html";
            }
            case "xls" -> {
                readResult = readXlsAsHtml(fileInfo.getFilePath());
                previewType = "html";
            }
            case "xlsx" -> {
                readResult = readXlsxAsHtml(fileInfo.getFilePath());
                previewType = "html";
            }
            case "ppt" -> {
                readResult = readPptAsHtml(fileInfo.getFilePath());
                previewType = "html";
            }
            case "pptx" -> {
                readResult = readPptxAsHtml(fileInfo.getFilePath());
                previewType = "html";
            }
            case "pdf" -> {
                readResult = new PreviewReadResult("", false);
                previewType = "pdf";
            }
            default -> readResult = readTextFile(fileInfo.getFilePath());
        }

        return new FilePreviewResponse(
                fileInfo.getFileName(),
                previewType,
                readResult.content,
                readResult.truncated
        );
    }

    public FileInfo getFile(Long id) {
        FileInfo fileInfo = fileStore.get(id);
        if (fileInfo == null) {
            throw new RuntimeException("文件不存在");
        }
        return fileInfo;
    }

    public FileInfo saveContent(Long id, String content, String previewType) throws IOException {
        FileInfo fileInfo = fileStore.get(id);
        if (fileInfo == null) {
            throw new RuntimeException("文件不存在");
        }

        String safeContent = content == null ? "" : content;
        String suffix = fileInfo.getSuffix() == null ? "" : fileInfo.getSuffix().toLowerCase();

        if (DIRECT_EDITABLE_SUFFIX.contains(suffix)) {
            Path path = Paths.get(fileInfo.getFilePath());
            Files.writeString(path, safeContent, StandardCharsets.UTF_8);
            refreshFileInfoMeta(fileInfo, path, fileInfo.getFileName(), suffix);
            persistFileStore();
            return fileInfo;
        }

        if ("html".equalsIgnoreCase(previewType)) {
            String originalName = fileInfo.getFileName();
            String baseName = stripExtension(originalName);
            String newFileName = baseName + ".html";

            Path oldPath = Paths.get(fileInfo.getFilePath());
            Path newPath = Paths.get(UPLOAD_DIR, UUID.randomUUID() + "_" + newFileName);
            Files.writeString(newPath, safeContent, StandardCharsets.UTF_8);

            if (Files.exists(oldPath) && !oldPath.equals(newPath)) {
                Files.deleteIfExists(oldPath);
            }

            refreshFileInfoMeta(fileInfo, newPath, newFileName, "html");
            persistFileStore();
            return fileInfo;
        }

        throw new RuntimeException("当前文件类型暂不支持在线编辑保存");
    }

    public void delete(Long id) throws IOException {
        FileInfo fileInfo = fileStore.get(id);
        if (fileInfo == null) {
            throw new RuntimeException("文件不存在");
        }

        Path filePath = Paths.get(fileInfo.getFilePath());
        Files.deleteIfExists(filePath);
        fileStore.remove(id);
        persistFileStore();
    }

    private void refreshFileInfoMeta(FileInfo fileInfo, Path path, String fileName, String suffix) throws IOException {
        fileInfo.setFileName(fileName);
        fileInfo.setSuffix(suffix);
        fileInfo.setFilePath(path.toAbsolutePath().toString());
        fileInfo.setFileSize(Files.size(path));
        fileInfo.setUploadTime(dateFormat.format(new Date()));
    }

    private PreviewReadResult readTextFile(String filePath) throws IOException {
        StringBuilder sb = new StringBuilder();
        boolean truncated = false;
        int lineCount = 0;

        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(Files.newInputStream(Paths.get(filePath)), StandardCharsets.UTF_8))) {

            String line;
            while ((line = reader.readLine()) != null) {
                sb.append(line).append("\n");
                lineCount++;

                if (lineCount >= MAX_PREVIEW_LINES || sb.length() >= MAX_PREVIEW_CHARS) {
                    truncated = true;
                    break;
                }
            }
        }

        if (truncated) {
            sb.append("\n... 内容过长，预览已截断 ...");
        }

        return new PreviewReadResult(sb.toString(), truncated);
    }

    private PreviewReadResult readDocFile(String filePath) throws IOException {
        if (isZipBasedOffice(filePath)) {
            PreviewReadResult docxResult = readDocxAsHtml(filePath);
            return limitPreview(stripHtml(docxResult.content));
        }

        try (InputStream in = Files.newInputStream(Paths.get(filePath));
             HWPFDocument document = new HWPFDocument(in);
             WordExtractor extractor = new WordExtractor(document)) {

            return limitPreview(extractor.getText());
        } catch (Exception e) {
            throw new RuntimeException("Word(.doc) 文件解析失败，可能是损坏文件或扩展名与实际格式不一致");
        }
    }

    private PreviewReadResult readDocxAsHtml(String filePath) throws IOException {
        if (!isZipBasedOffice(filePath)) {
            return readDocFileAsFallback(filePath);
        }

        try (InputStream in = Files.newInputStream(Paths.get(filePath));
             XWPFDocument document = new XWPFDocument(in)) {

            StringBuilder html = new StringBuilder();
            boolean[] truncated = {false};
            int[] imageCount = {0};

            html.append("<div class=\"docx-preview\">");

            for (IBodyElement element : document.getBodyElements()) {
                if (truncated[0]) {
                    break;
                }

                if (element.getElementType() == BodyElementType.PARAGRAPH) {
                    appendParagraphHtml(html, (XWPFParagraph) element, imageCount, truncated);
                } else if (element.getElementType() == BodyElementType.TABLE) {
                    appendWordTableHtml(html, (XWPFTable) element);
                }

                if (html.length() > MAX_HTML_CHARS) {
                    truncated[0] = true;
                }
            }

            if (truncated[0]) {
                html.append("<p class=\"preview-note\">... 内容过长，预览已截断 ...</p>");
            }

            html.append("</div>");
            return new PreviewReadResult(html.toString(), truncated[0]);
        } catch (Exception e) {
            throw new RuntimeException("Word(.docx) 文件解析失败");
        }
    }

    private PreviewReadResult readDocFileAsFallback(String filePath) throws IOException {
        try (InputStream in = Files.newInputStream(Paths.get(filePath));
             HWPFDocument document = new HWPFDocument(in);
             WordExtractor extractor = new WordExtractor(document)) {
            return limitPreview(extractor.getText());
        } catch (Exception ex) {
            throw new RuntimeException("Word 文件解析失败，扩展名与实际格式可能不一致");
        }
    }

    private PreviewReadResult readXlsxAsHtml(String filePath) throws IOException {
        if (!isZipBasedOffice(filePath)) {
            return readXlsAsHtml(filePath);
        }

        try (InputStream in = Files.newInputStream(Paths.get(filePath));
             Workbook workbook = new XSSFWorkbook(in)) {
            return workbookToHtml(workbook);
        } catch (Exception e) {
            throw new RuntimeException("Excel(.xlsx) 文件解析失败");
        }
    }

    private PreviewReadResult readXlsAsHtml(String filePath) throws IOException {
        if (isZipBasedOffice(filePath)) {
            return readXlsxAsHtml(filePath);
        }

        try (InputStream in = Files.newInputStream(Paths.get(filePath));
             Workbook workbook = new HSSFWorkbook(in)) {
            return workbookToHtml(workbook);
        } catch (Exception e) {
            throw new RuntimeException("Excel(.xls) 文件解析失败");
        }
    }

    private PreviewReadResult workbookToHtml(Workbook workbook) {
        DataFormatter formatter = new DataFormatter();
        StringBuilder html = new StringBuilder();
        boolean truncated = false;

        html.append("<div class=\"excel-preview\">");

        for (int s = 0; s < workbook.getNumberOfSheets(); s++) {
            if (html.length() > MAX_HTML_CHARS) {
                truncated = true;
                break;
            }

            Sheet sheet = workbook.getSheetAt(s);
            html.append("<h3 class=\"sheet-title\">工作表: ")
                    .append(escapeHtml(sheet.getSheetName()))
                    .append("</h3>");
            html.append("<table class=\"docx-table excel-table\">");

            int start = sheet.getFirstRowNum();
            int end = sheet.getLastRowNum();
            for (int r = start; r <= end; r++) {
                Row row = sheet.getRow(r);
                if (row == null) {
                    continue;
                }

                html.append("<tr>");
                int firstCell = row.getFirstCellNum();
                int lastCell = row.getLastCellNum();
                if (firstCell >= 0 && lastCell >= 0) {
                    for (int c = firstCell; c < lastCell; c++) {
                        Cell cell = row.getCell(c);
                        String value = cell == null ? "" : formatter.formatCellValue(cell);
                        html.append("<td>")
                                .append(escapeHtml(value == null ? "" : value))
                                .append("</td>");
                    }
                }
                html.append("</tr>");

                if (html.length() > MAX_HTML_CHARS) {
                    truncated = true;
                    break;
                }
            }

            html.append("</table>");
            if (truncated) {
                break;
            }
        }

        if (truncated) {
            html.append("<p class=\"preview-note\">... 内容过长，预览已截断 ...</p>");
        }

        html.append("</div>");
        return new PreviewReadResult(html.toString(), truncated);
    }

    private PreviewReadResult readPptxAsHtml(String filePath) throws IOException {
        if (!isZipBasedOffice(filePath)) {
            return readPptAsHtml(filePath);
        }

        try (InputStream in = Files.newInputStream(Paths.get(filePath));
             XMLSlideShow slideShow = new XMLSlideShow(in)) {

            StringBuilder html = new StringBuilder();
            boolean truncated = false;
            int imageCount = 0;

            html.append("<div class=\"ppt-preview\">");

            List<XSLFSlide> slides = slideShow.getSlides();
            for (int i = 0; i < slides.size(); i++) {
                if (html.length() > MAX_HTML_CHARS) {
                    truncated = true;
                    break;
                }

                XSLFSlide slide = slides.get(i);
                html.append("<section class=\"ppt-slide\"><h3>第 ")
                        .append(i + 1)
                        .append(" 页</h3>");

                for (XSLFShape shape : slide.getShapes()) {
                    if (shape instanceof XSLFTextShape textShape) {
                        String text = textShape.getText();
                        if (text != null && !text.isBlank()) {
                            html.append("<p>").append(escapeHtml(text).replace("\n", "<br/>"))
                                    .append("</p>");
                        }
                    } else if (shape instanceof XSLFPictureShape pictureShape) {
                        if (imageCount >= MAX_EMBED_IMAGES) {
                            html.append("<div class=\"image-note\">[图片较多，后续已省略]</div>");
                            break;
                        }
                        XSLFPictureData pd = pictureShape.getPictureData();
                        if (pd == null || pd.getData() == null) {
                            continue;
                        }
                        if (pd.getData().length > MAX_IMAGE_BYTES) {
                            html.append("<div class=\"image-note\">[图片过大，已省略]</div>");
                            continue;
                        }
                        String base64 = Base64.getEncoder().encodeToString(pd.getData());
                        html.append("<img class=\"ppt-image\" src=\"data:")
                                .append(pd.getContentType())
                                .append(";base64,")
                                .append(base64)
                                .append("\" alt=\"ppt-image\" />");
                        imageCount++;
                    }

                    if (html.length() > MAX_HTML_CHARS) {
                        truncated = true;
                        break;
                    }
                }

                html.append("</section>");
                if (truncated) {
                    break;
                }
            }

            if (truncated) {
                html.append("<p class=\"preview-note\">... 内容过长，预览已截断 ...</p>");
            }

            html.append("</div>");
            return new PreviewReadResult(html.toString(), truncated);
        } catch (Exception e) {
            throw new RuntimeException("PowerPoint(.pptx) 文件解析失败");
        }
    }

    private PreviewReadResult readPptAsHtml(String filePath) throws IOException {
        if (isZipBasedOffice(filePath)) {
            return readPptxAsHtml(filePath);
        }

        try (InputStream in = Files.newInputStream(Paths.get(filePath));
             HSLFSlideShow slideShow = new HSLFSlideShow(in)) {

            StringBuilder html = new StringBuilder();
            boolean truncated = false;
            int imageCount = 0;

            html.append("<div class=\"ppt-preview\">");

            List<HSLFSlide> slides = slideShow.getSlides();
            for (int i = 0; i < slides.size(); i++) {
                if (html.length() > MAX_HTML_CHARS) {
                    truncated = true;
                    break;
                }

                HSLFSlide slide = slides.get(i);
                html.append("<section class=\"ppt-slide\"><h3>第 ")
                        .append(i + 1)
                        .append(" 页</h3>");

                for (HSLFShape shape : slide.getShapes()) {
                    if (shape instanceof HSLFTextShape textShape) {
                        String text = textShape.getText();
                        if (text != null && !text.isBlank()) {
                            html.append("<p>")
                                    .append(escapeHtml(text).replace("\n", "<br/>"))
                                    .append("</p>");
                        }
                    } else if (shape instanceof HSLFPictureShape pictureShape) {
                        if (imageCount >= MAX_EMBED_IMAGES) {
                            html.append("<div class=\"image-note\">[图片较多，后续已省略]</div>");
                            break;
                        }
                        HSLFPictureData pd = pictureShape.getPictureData();
                        if (pd == null || pd.getData() == null) {
                            continue;
                        }
                        if (pd.getData().length > MAX_IMAGE_BYTES) {
                            html.append("<div class=\"image-note\">[图片过大，已省略]</div>");
                            continue;
                        }

                        String ext = pd.getType() == null ? "png" : pd.getType().extension;
                        String mime = mimeTypeByExtension(ext);
                        String base64 = Base64.getEncoder().encodeToString(pd.getData());
                        html.append("<img class=\"ppt-image\" src=\"data:")
                                .append(mime)
                                .append(";base64,")
                                .append(base64)
                                .append("\" alt=\"ppt-image\" />");
                        imageCount++;
                    }

                    if (html.length() > MAX_HTML_CHARS) {
                        truncated = true;
                        break;
                    }
                }

                html.append("</section>");
                if (truncated) {
                    break;
                }
            }

            if (truncated) {
                html.append("<p class=\"preview-note\">... 内容过长，预览已截断 ...</p>");
            }

            html.append("</div>");
            return new PreviewReadResult(html.toString(), truncated);
        } catch (Exception e) {
            throw new RuntimeException("PowerPoint(.ppt) 文件解析失败");
        }
    }

    private void appendParagraphHtml(StringBuilder html, XWPFParagraph paragraph, int[] imageCount, boolean[] truncated) {
        html.append("<p>");

        List<XWPFRun> runs = paragraph.getRuns();
        if (runs == null || runs.isEmpty()) {
            html.append("&nbsp;</p>");
            return;
        }

        for (XWPFRun run : runs) {
            if (truncated[0]) {
                break;
            }

            String text = run.text();
            if (text != null && !text.isEmpty()) {
                html.append(escapeHtml(text).replace("\n", "<br/>"));
            }

            for (XWPFPicture picture : run.getEmbeddedPictures()) {
                if (truncated[0]) {
                    break;
                }
                appendWordPictureHtml(html, picture, imageCount);
            }

            if (html.length() > MAX_HTML_CHARS) {
                truncated[0] = true;
            }
        }

        html.append("</p>");
    }

    private void appendWordTableHtml(StringBuilder html, XWPFTable table) {
        html.append("<table class=\"docx-table\">");

        for (XWPFTableRow row : table.getRows()) {
            html.append("<tr>");
            for (XWPFTableCell cell : row.getTableCells()) {
                html.append("<td>")
                        .append(escapeHtml(cell.getText() == null ? "" : cell.getText()).replace("\n", "<br/>"))
                        .append("</td>");
            }
            html.append("</tr>");
        }

        html.append("</table>");
    }

    private void appendWordPictureHtml(StringBuilder html, XWPFPicture picture, int[] imageCount) {
        if (imageCount[0] >= MAX_EMBED_IMAGES) {
            html.append("<div class=\"image-note\">[图片较多，后续已省略]</div>");
            return;
        }

        XWPFPictureData pictureData = picture.getPictureData();
        if (pictureData == null || pictureData.getData() == null || pictureData.getData().length == 0) {
            return;
        }

        byte[] bytes = pictureData.getData();
        if (bytes.length > MAX_IMAGE_BYTES) {
            html.append("<div class=\"image-note\">[图片过大，已省略]</div>");
            return;
        }

        String mime = mimeTypeByExtension(pictureData.suggestFileExtension());
        String base64 = Base64.getEncoder().encodeToString(bytes);

        html.append("<img class=\"docx-image\" src=\"data:")
                .append(mime)
                .append(";base64,")
                .append(base64)
                .append("\" alt=\"docx-image\" />");

        imageCount[0]++;
    }

    private String mimeTypeByExtension(String ext) {
        if (ext == null) {
            return "image/png";
        }
        return switch (ext.toLowerCase()) {
            case "png" -> "image/png";
            case "jpg", "jpeg" -> "image/jpeg";
            case "gif" -> "image/gif";
            case "bmp" -> "image/bmp";
            case "webp" -> "image/webp";
            case "svg" -> "image/svg+xml";
            default -> "image/png";
        };
    }

    private boolean isZipBasedOffice(String filePath) throws IOException {
        byte[] header = new byte[4];
        try (InputStream in = Files.newInputStream(Paths.get(filePath))) {
            int read = in.read(header);
            return read == 4
                    && header[0] == 0x50
                    && header[1] == 0x4B
                    && header[2] == 0x03
                    && header[3] == 0x04;
        }
    }

    private PreviewReadResult limitPreview(String rawContent) {
        if (rawContent == null) {
            return new PreviewReadResult("", false);
        }

        String normalized = rawContent.replace("\r\n", "\n").replace('\r', '\n');
        String[] lines = normalized.split("\n", -1);

        StringBuilder sb = new StringBuilder();
        boolean truncated = false;

        int maxLines = Math.min(lines.length, MAX_PREVIEW_LINES);
        for (int i = 0; i < maxLines; i++) {
            sb.append(lines[i]).append("\n");
            if (sb.length() >= MAX_PREVIEW_CHARS) {
                sb.setLength(MAX_PREVIEW_CHARS);
                truncated = true;
                break;
            }
        }

        if (!truncated && lines.length > MAX_PREVIEW_LINES) {
            truncated = true;
        }
        if (!truncated && normalized.length() > MAX_PREVIEW_CHARS) {
            truncated = true;
        }

        if (truncated) {
            sb.append("\n... 内容过长，预览已截断 ...");
        }

        return new PreviewReadResult(sb.toString(), truncated);
    }

    private String escapeHtml(String text) {
        return text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\"", "&quot;")
                .replace("'", "&#39;");
    }

    private String stripHtml(String html) {
        return html
                .replaceAll("<br\\s*/?>", "\n")
                .replaceAll("<[^>]+>", "")
                .replace("&nbsp;", " ")
                .replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&quot;", "\"")
                .replace("&#39;", "'");
    }

    private String stripExtension(String fileName) {
        if (fileName == null || !fileName.contains(".")) {
            return fileName == null ? "untitled" : fileName;
        }
        return fileName.substring(0, fileName.lastIndexOf('.'));
    }

    private String getSuffix(String fileName) {
        if (fileName == null || !fileName.contains(".")) {
            return "";
        }
        return fileName.substring(fileName.lastIndexOf('.') + 1);
    }

    private synchronized void persistFileStore() throws IOException {
        Path indexPath = Paths.get(UPLOAD_DIR, INDEX_FILE);
        List<FileInfo> data = fileStore.values().stream()
                .sorted(Comparator.comparing(FileInfo::getId))
                .collect(Collectors.toList());
        objectMapper.writerWithDefaultPrettyPrinter().writeValue(indexPath.toFile(), data);
    }

    private synchronized void loadFileStore(Path uploadPath) throws IOException {
        Path indexPath = uploadPath.resolve(INDEX_FILE);
        if (Files.exists(indexPath)) {
            List<FileInfo> list = objectMapper.readValue(indexPath.toFile(), new TypeReference<List<FileInfo>>() {
            });
            long maxId = 0L;
            for (FileInfo item : list) {
                if (item == null || item.getId() == null || item.getFilePath() == null) {
                    continue;
                }
                if (!Files.exists(Paths.get(item.getFilePath()))) {
                    continue;
                }
                fileStore.put(item.getId(), item);
                maxId = Math.max(maxId, item.getId());
            }
            idGenerator.set(maxId + 1);
            return;
        }

        recoverFromUploadDirectory(uploadPath);
        if (!fileStore.isEmpty()) {
            persistFileStore();
        }
    }

    private void recoverFromUploadDirectory(Path uploadPath) throws IOException {
        List<Path> files;
        try (Stream<Path> stream = Files.list(uploadPath)) {
            files = stream
                    .filter(Files::isRegularFile)
                    .filter(path -> !INDEX_FILE.equals(path.getFileName().toString()))
                    .sorted(Comparator.comparingLong(path -> path.toFile().lastModified()))
                    .collect(Collectors.toList());
        }

        long id = 1L;
        for (Path path : files) {
            String storedName = path.getFileName().toString();
            String originalName = storedName.contains("_")
                    ? storedName.substring(storedName.indexOf('_') + 1)
                    : storedName;

            FileInfo fileInfo = new FileInfo(
                    id,
                    originalName,
                    path.toAbsolutePath().toString(),
                    getSuffix(originalName),
                    Files.size(path),
                    dateFormat.format(new Date(path.toFile().lastModified()))
            );
            fileStore.put(id, fileInfo);
            id++;
        }
        idGenerator.set(id);
    }

    private static class PreviewReadResult {
        private final String content;
        private final boolean truncated;

        private PreviewReadResult(String content, boolean truncated) {
            this.content = content;
            this.truncated = truncated;
        }
    }
}