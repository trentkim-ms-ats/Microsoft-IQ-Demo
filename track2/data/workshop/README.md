# 원본 워크샵 Track 2 데이터 패키지

원본 `trentkim-ms-ats/microsoft-iq-workshop`의 고정 커밋 `b16d5fd8ed481f86eb47d5d4625268ef65a7793b`에서 사용자가 요청하여 Track2 콘텐츠 정의와 생성된 데이터 자산을 가져왔습니다. 재배포 권리와 저장소 라이선스는 [SOURCES.md](../../../SOURCES.md)를 확인하세요.

## 포함 범위

- `content_definitions/`: 인물, 사실, SharePoint/OneDrive 문서, Outlook 메일, Teams 스레드의 원본 정의 JSON 6개
- `generated/sharepoint/`: DOCX 문서 15개
- `generated/onedrive/`: DOCX 문서 12개
- `generated/outlook/`: EML 메일 15개와 메시지 JSON
- `generated/teams/`: 18개 스레드, 총 55개 메시지
- `generated/manifests/`: 전체 카탈로그, CSV manifest, 기대 건수·키워드 커버리지 manifest

전체 패키지는 60개 업무 항목이며, 19개 기준 시드 명세에 필요한 콘텐츠를 포함합니다. Teams의 55개 메시지는 18개 업무 항목의 일부이지 추가 항목 수가 아닙니다.

## 라이브 게시

저장소 루트에서 [Track2 라이브 안내](../../README.md)를 따르세요. 게시 스크립트는 이 패키지의 전체 카탈로그를 사용하여 격리 테넌트에 파일을 업로드하고, 이메일을 게시자 본인에게 보내며, Teams 메시지를 지정 채널에 게시합니다. 별도 프로비저닝 스크립트는 지정된 폴더와 채널을 구성할 수 있지만 관리자 동의 및 유효 접근 권한 확인을 대체하지 않으며, 게시 스크립트는 권한을 변경하거나 검색 성공을 보증하지 않습니다.

오프라인 corpus 로더와 저장된 시뮬레이션 출력은 제공하지 않습니다. 이 패키지를 실제 M365에 게시하지 않은 상태로 Graph 검색의 증거로 사용하지 마세요.
