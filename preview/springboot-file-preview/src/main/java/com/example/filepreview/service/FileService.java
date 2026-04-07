package com.example.filepreview.service;

import com.example.filepreview.model.FileInfo;
import com.example.filepreview.model.FilePreviewResponse;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Date;
import java.util.HashMap;
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

    private static final Set<String> TEXT_PREVIEWABLE_SUFFIX = Set.of(
            "txt", "md", "json", "xml", "csv", "log",
            "java", "js", "ts", "vue", "html", "css",
            "sql", "py", "yml", "yaml", "properties"
    );

    private static final Set<String> ONLYOFFICE_SUFFIX = Set.of(
            "doc", "docx", "xls", "xlsx", "ppt", "pptx"
    );

    private static final Set<String> DIRECT_EDITABLE_SUFFIX = Set.of(
            "txt", "md", "json", "xml", "csv", "log",
            "java", "js", "ts", "vue", "html", "htm", "css",
            "sql", "py", "yml", "yaml", "properties"
    );

    private static final int MAX_PREVIEW_LINES = 500;
    private static final int MAX_PREVIEW_CHARS = 50000;

    private final Map<Long, FileInfo> fileStore = new ConcurrentHashMap<>();
    private final AtomicLong idGenerator = new AtomicLong(1);
    private final ObjectMapper objectMapper = new ObjectMapper();
    private final SimpleDateFormat dateFormat = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss");
    private final HttpClient httpClient = HttpClient.newHttpClient();

    @Value("${onlyoffice.document-server-url:http://localhost:8088}")
    private String onlyOfficeServerUrl;

    @Value("${onlyoffice.public-base-url:http://localhost:8080}")
    private String publicBaseUrl;

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
        if (originalFilename == null || originalFilename.isBlank()) {
            originalFilename = "unnamed";
        }

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

        String suffix = normalizeSuffix(fileInfo.getSuffix());
        if (ONLYOFFICE_SUFFIX.contains(suffix)) {
            return new FilePreviewResponse(fileInfo.getFileName(), "onlyoffice", "", false);
        }
        if ("pdf".equals(suffix)) {
            return new FilePreviewResponse(fileInfo.getFileName(), "pdf", "", false);
        }
        if (TEXT_PREVIEWABLE_SUFFIX.contains(suffix)) {
            PreviewReadResult readResult = readTextFile(fileInfo.getFilePath());
            return new FilePreviewResponse(fileInfo.getFileName(), "text", readResult.content, readResult.truncated);
        }

        return new FilePreviewResponse(fileInfo.getFileName(), "text", "当前文件类型暂不支持文本预览", false);
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

        String suffix = normalizeSuffix(fileInfo.getSuffix());
        if (!DIRECT_EDITABLE_SUFFIX.contains(suffix)) {
            throw new RuntimeException("当前文件类型暂不支持在线编辑保存，Office 文件请在 OnlyOffice 中保存");
        }

        String safeContent = content == null ? "" : content;
        Path path = Paths.get(fileInfo.getFilePath());
        Files.writeString(path, safeContent, StandardCharsets.UTF_8);

        refreshFileInfoMeta(fileInfo, path, fileInfo.getFileName(), suffix);
        persistFileStore();
        return fileInfo;
    }

    public Map<String, Object> buildOnlyOfficeConfig(Long id, String mode) {
        FileInfo fileInfo = getFile(id);
        String suffix = normalizeSuffix(fileInfo.getSuffix());
        if (!ONLYOFFICE_SUFFIX.contains(suffix)) {
            throw new RuntimeException("当前文件不是 Office 文档");
        }

        String editorMode = "edit".equalsIgnoreCase(mode) ? "edit" : "view";

        String server = stripTrailingSlash(onlyOfficeServerUrl);
        String base = stripTrailingSlash(publicBaseUrl);

        Map<String, Object> document = new HashMap<>();
        document.put("title", fileInfo.getFileName());
        document.put("url", base + "/api/files/" + id + "/raw");
        document.put("fileType", suffix);
        document.put("key", buildDocKey(fileInfo));

        Map<String, Object> permissions = new HashMap<>();
        permissions.put("edit", true);
        permissions.put("download", true);
        permissions.put("print", true);
        permissions.put("comment", true);
        permissions.put("copy", true);
        document.put("permissions", permissions);

        Map<String, Object> editorConfig = new HashMap<>();
        editorConfig.put("mode", editorMode);
        editorConfig.put("lang", "zh-CN");
        editorConfig.put("callbackUrl", base + "/api/files/onlyoffice/callback/" + id);

        Map<String, Object> user = new HashMap<>();
        user.put("id", "local-user");
        user.put("name", "本地用户");
        editorConfig.put("user", user);

        Map<String, Object> config = new HashMap<>();
        config.put("documentType", documentTypeBySuffix(suffix));
        config.put("type", "desktop");
        config.put("document", document);
        config.put("editorConfig", editorConfig);

        Map<String, Object> wrapper = new HashMap<>();
        wrapper.put("serverUrl", server);
        wrapper.put("config", config);
        return wrapper;
    }

    public int handleOnlyOfficeCallback(Long id, Map<String, Object> payload) throws IOException {
        FileInfo fileInfo = getFile(id);

        Object statusObj = payload == null ? null : payload.get("status");
        int status = statusObj instanceof Number ? ((Number) statusObj).intValue() : -1;
        if (status != 2 && status != 6) {
            return 0;
        }

        Object urlObj = payload.get("url");
        if (!(urlObj instanceof String url) || url.isBlank()) {
            return 0;
        }

        Path oldPath = Paths.get(fileInfo.getFilePath());
        String originalName = fileInfo.getFileName();
        Path newPath = Paths.get(UPLOAD_DIR, UUID.randomUUID() + "_" + originalName);

        HttpRequest request = HttpRequest.newBuilder(URI.create(url)).GET().build();
        HttpResponse<InputStream> response;
        try {
            response = httpClient.send(request, HttpResponse.BodyHandlers.ofInputStream());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new RuntimeException("获取在线编辑保存结果失败");
        }

        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new RuntimeException("获取在线编辑保存结果失败");
        }

        try (InputStream in = response.body()) {
            Files.copy(in, newPath, StandardCopyOption.REPLACE_EXISTING);
        }

        if (!oldPath.equals(newPath)) {
            Files.deleteIfExists(oldPath);
        }

        refreshFileInfoMeta(fileInfo, newPath, originalName, normalizeSuffix(fileInfo.getSuffix()));
        persistFileStore();
        return 0;
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

    private String normalizeSuffix(String suffix) {
        return suffix == null ? "" : suffix.toLowerCase();
    }

    private String documentTypeBySuffix(String suffix) {
        return switch (suffix) {
            case "doc", "docx" -> "word";
            case "xls", "xlsx" -> "cell";
            case "ppt", "pptx" -> "slide";
            default -> "word";
        };
    }

    private String buildDocKey(FileInfo fileInfo) {
        return fileInfo.getId() + "_" + fileInfo.getFileSize() + "_" + fileInfo.getUploadTime().hashCode();
    }

    private String stripTrailingSlash(String url) {
        if (url == null || url.isBlank()) {
            return "";
        }
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }

    private void refreshFileInfoMeta(FileInfo fileInfo, Path path, String fileName, String suffix) throws IOException {
        fileInfo.setFileName(fileName);
        fileInfo.setSuffix(suffix);
        fileInfo.setFilePath(path.toAbsolutePath().toString());
        fileInfo.setFileSize(Files.size(path));
        fileInfo.setUploadTime(dateFormat.format(new Date()));
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
