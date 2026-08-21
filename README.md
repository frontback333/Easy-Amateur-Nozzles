# Easy Amateur Nozzles

PySide6(Qt Widgets) 기반 로켓 노즐 설계 앱 골격입니다. 현재는 **Aerospike (Angelino)** 흐름만 활성화되어 있습니다.

```powershell
pip install -r requirements.txt
python widget.py
```

테스트는 다음 명령으로 실행합니다.

```powershell
python -m unittest -v
```

## 현재 지원 기능

- Angelino(1964) 근사식을 이용한 축대칭 Aerospike Plug contour 계산
- 연소실 압력, 설계 출구 압력, 비열비, geometric throat 면적, 절단 비율 입력
- Lip/Plug 수렴부와 일정 throat 길이(`lₜ`)를 포함한 형상 구성
- Lip 내·외벽 및 solid Plug 좌표의 CSV 내보내기
- 절단 비율 0%에서 출구 Mach(`Mₑ`)의 끝점을 보존하는 contour 계산
- Wireframe, point cloud, smooth surface 3D 미리보기와 Lip/Plug 표시 제어
- 2D contour 선 굵기 조절

Angelino(1964) 근사법으로 내부 Plug contour를 계산합니다. 유동은 +x 방향이며, Lip은 Plug 기둥의 시작점에서 함께 시작합니다. Geometric throat 면적 Aₜ는 Lip 끝점 A와 Plug 시작점 B 사이의 환형 빈 공간으로 정하며, 계산된 `lₜ = |AB|`를 결과로 표시합니다. `Throat 길이`는 공통 수렴부의 축 방향 길이입니다. Lip pipe 지름과 Plug 기둥 지름을 따로 입력해 Lip 내·외벽과 완전한 solid Plug 기둥/contour를 별도 좌표로 출력합니다. Me는 입력한 출구 압력 pₑ와 p₀, γ에서 계산되며, 입력한 M 스위프 단계 수로 M=1부터 Me까지 계산합니다.

논문은 Plug diverging contour만 정의하므로 Lip 수렴부, Plug 수렴부, Plug 기둥은 별도 기하 입력입니다. Plug 수렴부는 throat B 이전의 단순 직선 transition이며, Angelino diverging contour는 B에서 시작합니다. Lip만 입력 벽 두께를 갖는 중공 pipe이고, Plug는 truncated 끝과 기둥 끝을 포함해 완전히 막힌 solid입니다.

3D preview는 GPU OpenGL depth buffer와 MSAA를 사용하므로, 회전 중에도 표면 가림과 해상도가 유지됩니다. 2D contour 미리보기에서는 선 굵기를 조절해 작은 형상도 더 쉽게 확인할 수 있습니다.
