# 출처와 재배포 범위

## 확인한 기준

- 원본: <https://github.com/trentkim-ms-ats/microsoft-iq-workshop>
- 브랜치: `main`
- 참조 커밋: `759d48997debedb993c21add56c87597e8144194`
- 확인일: 2026-11-18
- 실제 트랙: Track1 FabricIQ, Track2 WorkIQ, Track3 WebIQ, Track4 FoundryIQ
- 위 커밋의 전체 파일 목록에서 `LICENSE`, `COPYING`, `NOTICE` 계열 파일을 찾지 못했고 루트 README에도 재배포 허락이 명시되어 있지 않았습니다. **공개 열람 가능하다는 이유로 복제 허용을 추정하지 않았습니다.**

Track1의 `track1/data/`에는 사용자가 요청하여 원본 저장소의 고정 커밋 `b16d5fd8ed481f86eb47d5d4625268ef65a7793b`에서 가져온 CSV 14개가 있습니다. 원본 코드·문서·배포 번들·이미지·발표 자료는 포함하지 않았습니다. 원본에 라이선스가 명시되어 있지 않으므로 CSV를 공개 배포하기 전에 권리를 확인하세요.

## 설계 사실을 확인한 문서

아래는 원문을 다시 배포하는 대신 역할·선행조건·제약을 파악하는 데 사용한 링크입니다.

| 범위 | 고정된 원본 링크 | 여기서 채택한 범위 |
| --- | --- | --- |
| 전체 | [README](https://github.com/trentkim-ms-ats/microsoft-iq-workshop/blob/759d48997debedb993c21add56c87597e8144194/README.md) | 트랙 순서, 세 근거를 구분하는 책임 |
| FabricIQ | [준비](https://github.com/trentkim-ms-ats/microsoft-iq-workshop/blob/759d48997debedb993c21add56c87597e8144194/track1/PREREQUISITES.md), [데이터 구조](https://github.com/trentkim-ms-ats/microsoft-iq-workshop/blob/759d48997debedb993c21add56c87597e8144194/track1/data/README.md) | Lakehouse·Ontology 필요조건, 결제/배송/상품 분석 주제 |
| WorkIQ | [준비](https://github.com/trentkim-ms-ats/microsoft-iq-workshop/blob/759d48997debedb993c21add56c87597e8144194/track2/PREREQUISITES.md), [배포 안내](https://github.com/trentkim-ms-ats/microsoft-iq-workshop/blob/759d48997debedb993c21add56c87597e8144194/track2/data/TRACK2_M365_Complete_Deployment_Guide.md) | 네 M365 소스, 실제 ACL 검증 필요, 읽기와 배포 권한 분리 |
| WebIQ | [준비](https://github.com/trentkim-ms-ats/microsoft-iq-workshop/blob/759d48997debedb993c21add56c87597e8144194/track3/PREREQUISITES.md) | 공개 검색어만 사용, citation·범위·한계 기록 |
| FoundryIQ | [준비](https://github.com/trentkim-ms-ats/microsoft-iq-workshop/blob/759d48997debedb993c21add56c87597e8144194/track4/PREREQUISITES.md) | 세 소스 결합, 부분응답/차단, Responses API 경계 |

## 이 저장소에서 새로 만든 자료

Track2~4의 업무 문서와 fixture는 독립 작성한 예제이며 원본 Track1 데이터와 결합하지 않습니다. 원본의 완료 건수·학습 평가를 충족하는 패키지는 아닙니다.

외부 기관의 페이지 본문·상표 이미지·검색 결과는 저장하지 않았습니다. fixture에는 URL과 독립 작성한 용도만 있습니다. 실제 웹 콘텐츠를 수집·저장할 때는 해당 서비스 약관과 콘텐츠 권리를 별도로 확인하세요. 이 문서는 원본의 권리를 변경하거나 원본에 새 라이선스를 부여하지 않습니다.
