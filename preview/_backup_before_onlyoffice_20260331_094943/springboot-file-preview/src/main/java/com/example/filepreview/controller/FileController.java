package com.example.filepreview.controller;

import com.example.filepreview.model.FileInfo;
import com.example.filepreview.model.FilePreviewResponse;
import com.example.filepreview.model.FileSaveRequest;
import com.example.filepreview.model.Result;
import com.example.filepreview.service.FileService;
import org.springframework.core.io.InputStreamResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.FileInputStream;
import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Paths;
import java.util.List;

@RestController
@RequestMapping("/api/files")
public class FileController {

    private final FileService fileService;

    public FileController(FileService fileService) {
        this.fileService = fileService;
    }

    @PostMapping("/upload")
    public Result<FileInfo> upload(@RequestParam("file") MultipartFile file) {
        try {
            FileInfo fileInfo = fileService.upload(file);
            return Result.success(fileInfo);
        } catch (Exception e) {
            return Result.fail(e.getMessage());
        }
    }

    @GetMapping
    public Result<List<FileInfo>> list() {
        return Result.success(fileService.list());
    }

    @GetMapping("/{id}/preview")
    public Result<FilePreviewResponse> preview(@PathVariable Long id) {
        try {
            return Result.success(fileService.preview(id));
        } catch (Exception e) {
            return Result.fail(e.getMessage());
        }
    }

    @PostMapping("/{id}/save")
    public Result<FileInfo> save(@PathVariable Long id, @RequestBody FileSaveRequest request) {
        try {
            FileInfo fileInfo = fileService.saveContent(id, request == null ? null : request.getContent(), request == null ? null : request.getPreviewType());
            return Result.success(fileInfo);
        } catch (Exception e) {
            return Result.fail(e.getMessage());
        }
    }

    @DeleteMapping("/{id}")
    public Result<String> delete(@PathVariable Long id) {
        try {
            fileService.delete(id);
            return Result.success("删除成功");
        } catch (Exception e) {
            return Result.fail(e.getMessage());
        }
    }

    @GetMapping("/{id}/inline")
    public ResponseEntity<InputStreamResource> inline(@PathVariable Long id) throws IOException {
        FileInfo fileInfo = fileService.getFile(id);

        InputStreamResource resource = new InputStreamResource(
                new FileInputStream(Paths.get(fileInfo.getFilePath()).toFile())
        );

        String encodedFileName = URLEncoder.encode(fileInfo.getFileName(), StandardCharsets.UTF_8)
                .replaceAll("\\+", "%20");

        String suffix = fileInfo.getSuffix() == null ? "" : fileInfo.getSuffix().toLowerCase();
        String contentType = "application/octet-stream";
        if ("pdf".equals(suffix)) {
            contentType = "application/pdf";
        } else if ("html".equals(suffix) || "htm".equals(suffix)) {
            contentType = "text/html;charset=UTF-8";
        }

        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, "inline; filename*=UTF-8''" + encodedFileName)
                .contentType(MediaType.parseMediaType(contentType))
                .contentLength(fileInfo.getFileSize())
                .body(resource);
    }

    @GetMapping("/{id}/download")
    public ResponseEntity<InputStreamResource> download(@PathVariable Long id) throws IOException {
        FileInfo fileInfo = fileService.getFile(id);

        InputStreamResource resource = new InputStreamResource(
                new FileInputStream(Paths.get(fileInfo.getFilePath()).toFile())
        );

        String encodedFileName = URLEncoder.encode(fileInfo.getFileName(), StandardCharsets.UTF_8)
                .replaceAll("\\+", "%20");

        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename*=UTF-8''" + encodedFileName)
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .contentLength(fileInfo.getFileSize())
                .body(resource);
    }
}