# Easy Amateur Nozzles

PySide6(Qt Widgets) 기반 로켓 노즐 설계 앱 골격입니다. 현재는 **Aerospike (Angelino)** 흐름만 활성화되어 있습니다.

```powershell
pip install -r requirements.txt
python widget.py
```

Angelino(1964) 근사법으로 내부 Plug contour를 계산합니다. 유동은 +x 방향이며, Lip은 straight pipe 뒤에 Prandtl-Meyer 각 νe로 꺾이는 독립 수렴부입니다. Pipe 지름과 Plug 기둥 지름을 따로 입력해 Lip 내·외벽과 Plug 기둥/contour를 별도 좌표로 출력합니다.

논문은 Plug contour만 정의하므로 Lip pipe와 Plug 기둥은 별도 기하 입력입니다. 현재 Lip의 수렴부는 직선이고 Plug 기둥과 contour의 접속은 수직 shoulder입니다. 제조용 필렛은 다음 단계에서 추가할 수 있습니다.
