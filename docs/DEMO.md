# Track1 시연 순서

1. [원본 데이터](../track1/data/) 14개와 [지표 정의](../track1/README.md)를 확인합니다.
2. `python3 track1/workshop.py analyze`를 실행하고 `outputs/workshop-track1.json`에서 Q1~Q5 결과를 확인합니다.
3. Fabric Lakehouse의 `workshop_` 테이블과 Q1~Q5 쿼리 결과를 비교합니다. 검증 범위는 [검증 문서](VALIDATION.md)를 참고하세요.
4. Q2의 배송 지연 여부별 반품·불만 비율과 Q4의 품절 상품 포함 여부별 취소율·문의량을 비교합니다. 합성 데이터이므로 인과관계로 해석하지 않습니다.

Track2~4는 원본 Track1 데이터에 맞춘 통합 시연이 아직 준비되지 않았습니다. 실제 M365·웹 검색·Foundry 연결과 권한을 별도로 검증해야 하며, 남아 있는 독립 예제를 Track1의 근거로 제시하지 않습니다.
