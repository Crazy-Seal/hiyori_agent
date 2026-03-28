import fs from "node:fs";
import path from "node:path";
import AdmZip from "adm-zip";

const projectRoot = process.cwd();
const zipPath = path.join(projectRoot, "hiyori_pro_zh.zip");
const outputRoot = path.join(projectRoot, "public", "live2d");
const markerPath = path.join(outputRoot, "hiyori_pro_zh", "runtime", "hiyori_pro_t11.model3.json");
const cubismCorePath = path.join(projectRoot, "public", "live2dcubismcore.min.js");
const cubismCoreUrl = "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js";

const ensureCubismCore = async () => {
  if (fs.existsSync(cubismCorePath)) {
    console.log("Cubism Core 已存在，跳过下载。");
    return;
  }

  fs.mkdirSync(path.dirname(cubismCorePath), { recursive: true });
  const response = await fetch(cubismCoreUrl);
  if (!response.ok) {
    throw new Error(`下载 Cubism Core 失败: ${response.status} ${response.statusText}`);
  }

  const content = Buffer.from(await response.arrayBuffer());
  fs.writeFileSync(cubismCorePath, content);
  console.log("Cubism Core 下载完成。");
};

if (!fs.existsSync(zipPath)) {
  console.error(`未找到模型压缩包: ${zipPath}`);
  process.exit(1);
}

try {
  await ensureCubismCore();
} catch (error) {
  console.error(`准备 Cubism Core 失败: ${String(error)}`);
  process.exit(1);
}

if (fs.existsSync(markerPath)) {
  console.log("Live2D 资源已准备完成，跳过解压。");
  process.exit(0);
}

fs.mkdirSync(outputRoot, { recursive: true });

const zip = new AdmZip(zipPath);
zip.extractAllTo(outputRoot, true);

console.log("Live2D 资源解压完成。");
