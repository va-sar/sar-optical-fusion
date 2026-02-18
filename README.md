# SAR-Optical Fusion for Flood Monitoring

Fuses Sentinel-1 (SAR) and Sentinel-2 (optical) imagery to detect flooded areas. This tool produces human-interpretable flood maps by fusing SAR (cloud-penetrating) and optical (visually intuitive) data — ideal for rapid emergency response.
Validated on Danube River floods near Budapest. Achieves pixel alignment via RoMa + RANSAC.

![Example overlay](sample_data/fused_overlay.png)

## 🔧 Installation

### 1. Clone this repo
```bash
git clone https://github.com/yourname/SAROpticalFusion.git
cd SAROpticalFusion
````

### 2. Install RoMa at the validated commit
> ⚠️ **Critical**: Use commit `905ff76a3d8ac589e85cb2f04124bf75ab3ce1b9` for reproducible results.
```bash
git clone https://github.com/Parskatt/RoMa.git
cd RoMa
git checkout 905ff76a3d8ac589e85cb2f04124bf75ab3ce1b9
pip install -e .
cd ..
```

### 3. Install other dependencies
```bash
pip install -r requirements.txt
``` 

### 📥 **Input Requirements**

Data can be downloaded using Sentinel Downloader at https://github.com/va-sar/sentinel-downloader
#### 1. **Optical Image (`optical_image`)**
- **Type**: UINT8 RGB TIFF
- **Source**: Sentinel-2 L2A
- **Resolution**: Native  
- **Projection**: Any (will be matched to SAR via homography)  
- **Note**: Must be **cloud-free** over the area of interest



#### 2. **SAR Image (`sar_image`)**
- **Type**: FLOAT32 TIF 
- **Source**: Sentinel-1 GRD
- **Resolution**: Native
- **Format**: Linear power (not dB!) 

**Note on SAR Orientation**
This tool fuses SAR and optical images as-is. Sentinel-1 data may appear mirrored or rotated relative to optical imagery due to the side-looking radar geometry and orbit direction.
For intuitive visual alignment and to stay within RoMa’s rotation tolerance (~45°):
- Use orthorectified, north-up SAR products
- Apply geocoding + orientation correction before fusion 
>The included examples use raw Sentinel-1 GRD to demonstrate real-world challenges — including orientation mismatch.

### 🌍 **Sample Data Included**

To test the pipeline immediately, use the cropped **Budapest flood data** provided in this repo:

- **Optical**: [`sample_data/budapest_optical.tif`](sample_data/budapest_optical.tif)  
  (Sentinel-2, 01 Sep 2024, cloud-free RGB composite, before flood)
- **SAR**: [`sample_data/budapest_sar_vv.tif`](sample_data/budapest_sar_vv.tif)  
  (Sentinel-1 VV, 22 Sep 2024, linear power, during flood)

> 💡 Just update your `config.yaml`:
> ```yaml
> paths:
>   optical_image: "sample_data/budapest_optical.tif"
>   sar_image: "sample_data/budapest_sar_vv.tif"
> ```

This dataset captures the Danube River during peak flooding near Margit Island and Pest — ideal for validating flood detection.

Expected result is fused image, which you can find in `sample_data/fused_overlay.png`. Full images you can download using Sentinel-1/2 data downloader at https://github.com/va-sar/sentinel-downloader. GeoJSON file is in sample data directory.

### ▶️ **Usage**

1. **Prepare configuration**  
   Copy the example config and edit paths/parameters:
   ```bash
   cp config.example.yaml config.yaml
   nano config.yaml  # or open in your editor
   ```

2. **Set your data paths**  
   In `config.yaml`, update:
   ```yaml
   paths:
     optical_image: "path/to/your/sentinel2_rgb.tif"
     sar_image: "path/to/your/sentinel1_vv.tif"
   ```

3. **Tune processing (optional)**  
   Adjust key parameters:
   ```yaml
   processing:
     ransac:
       reproj_threshold: 0.2    # Max pixel error for inliers
     optical_sharpen:
       strength: 1.1            # 1.0 = no sharpening
   ```
   
4. **Run the fusion**
   ```bash
   python WarpProcessorFloat.py
   ```

5. **Inspect results**  
   Outputs are saved in timestamped folders under `runs/`:
   - `fused_overlay.png` — SAR overlaid on optical  
   - `matches_inliers.png` — verified keypoints
   - `sar_raw_uint8.png` — input SAR image converted to uint8
   - `temp_optical.png` — RoMa input sharpened optical image
   - `temp_sar.png` — RoMa input SAR image
   - `config.yaml` — exact parameters used (for reproducibility)



## 📚 References

- RoMa: [Parskatt et al., CVPR 2023](https://github.com/Parskatt/RoMa)  
- Sentinel Data: [Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu)
---
