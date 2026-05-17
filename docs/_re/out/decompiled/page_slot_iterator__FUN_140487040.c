// page_slot_iterator
// caller site (link va): 0x14048729c
// containing function: FUN_140487040 @ 0x140487040


ulonglong FUN_140487040(longlong param_1,undefined8 *param_2)

{
  uint uVar1;
  undefined1 auVar2 [16];
  ushort uVar3;
  undefined2 uVar4;
  char cVar5;
  char cVar6;
  char cVar7;
  char cVar8;
  char cVar9;
  char cVar10;
  char cVar11;
  char cVar12;
  char cVar13;
  char cVar14;
  char cVar15;
  char cVar16;
  char cVar17;
  char cVar18;
  char cVar19;
  char cVar20;
  char cVar21;
  int iVar22;
  longlong lVar23;
  ulonglong uVar24;
  char *pcVar25;
  longlong lVar26;
  undefined1 uVar27;
  ulonglong uVar28;
  longlong lVar29;
  uint uVar30;
  ulonglong uVar31;
  ulonglong uVar32;
  ulonglong uVar33;
  longlong lVar34;
  undefined1 auVar35 [16];
  undefined1 auVar39 [16];
  uint uVar40;
  ulonglong uVar41;
  char *local_88;
  uint local_80;
  int iStack_7c;
  char *local_78;
  uint local_70;
  int local_6c;
  char *local_68;
  uint local_60;
  undefined4 uStack_5c;
  char cVar36;
  char cVar37;
  char cVar38;
  
  FUN_140486f80();
  lVar23 = FUN_140c969e8(*param_2,0x2f);
  if (lVar23 == 0) {
    FUN_1401145b0(&local_88,param_2);
    pcVar25 = local_88;
    if ((int)local_80 < 0) {
      pcVar25 = (char *)FUN_1405111f0(&local_88);
    }
    if ((local_80 & 0x7fffffff) != 0) {
      uVar31 = (ulonglong)(local_80 & 0x7fffffff);
      do {
        iVar22 = tolower((int)*pcVar25);
        *pcVar25 = (char)iVar22;
        pcVar25 = pcVar25 + 1;
        uVar31 = uVar31 - 1;
      } while (uVar31 != 0);
    }
    uVar31 = 0xffffffffffffffff;
    do {
      uVar31 = uVar31 + 1;
    } while (local_88[uVar31] != '\0');
    uVar28 = 0xcbf29ce484222325;
    uVar24 = 0;
    uVar33 = uVar24;
    if (uVar31 != 0) {
      do {
        uVar28 = (uVar28 ^ (byte)local_88[uVar33]) * 0x100000001b3;
        uVar33 = uVar33 + 1;
      } while (uVar33 < uVar31);
    }
    auVar2._8_8_ = 0;
    auVar2._0_8_ = uVar28;
    uVar31 = SUB168(ZEXT816(0xde5fb9d2630458e9) * auVar2,0) +
             SUB168(ZEXT816(0xde5fb9d2630458e9) * auVar2,8);
    uVar33 = *(ulonglong *)(param_1 + 0x50);
    uVar28 = uVar31 >> 7;
    uVar27 = (undefined1)uVar31;
    uVar4 = CONCAT11(uVar27,uVar27);
    uVar30 = CONCAT22(uVar4,uVar4);
    uVar40 = uVar30 & 0x7f7f7f7f;
    uVar41 = CONCAT44(uVar30,uVar30) & 0x7f7f7f7f7f7f7f7f;
    uVar31 = uVar24;
    while( true ) {
      uVar28 = uVar28 & uVar33;
      lVar23 = *(longlong *)(param_1 + 0x38);
      pcVar25 = (char *)(uVar28 + lVar23);
      cVar5 = *pcVar25;
      cVar6 = pcVar25[1];
      cVar7 = pcVar25[2];
      cVar8 = pcVar25[3];
      cVar9 = pcVar25[4];
      cVar10 = pcVar25[5];
      cVar11 = pcVar25[6];
      cVar12 = pcVar25[7];
      cVar13 = pcVar25[8];
      cVar14 = pcVar25[9];
      cVar15 = pcVar25[10];
      cVar16 = pcVar25[0xb];
      cVar17 = pcVar25[0xc];
      cVar18 = pcVar25[0xd];
      cVar19 = pcVar25[0xe];
      cVar20 = pcVar25[0xf];
      cVar21 = (char)uVar40;
      auVar35[0] = -(cVar21 == cVar5);
      cVar36 = (char)(uVar40 >> 8);
      auVar35[1] = -(cVar36 == cVar6);
      auVar35[2] = -((char)(uVar41 >> 0x10) == cVar7);
      auVar35[3] = -((char)(uVar41 >> 0x18) == cVar8);
      auVar35[4] = -((char)(uVar41 >> 0x20) == cVar9);
      auVar35[5] = -((char)(uVar41 >> 0x28) == cVar10);
      auVar35[6] = -((char)(uVar41 >> 0x30) == cVar11);
      auVar35[7] = -((char)(uVar41 >> 0x38) == cVar12);
      auVar35[8] = -(cVar21 == cVar13);
      auVar35[9] = -(cVar36 == cVar14);
      cVar37 = (char)(uVar40 >> 0x10);
      auVar35[10] = -(cVar37 == cVar15);
      cVar38 = (char)(uVar40 >> 0x18);
      auVar35[0xb] = -(cVar38 == cVar16);
      auVar35[0xc] = -(cVar21 == cVar17);
      auVar35[0xd] = -(cVar36 == cVar18);
      auVar35[0xe] = -(cVar37 == cVar19);
      auVar35[0xf] = -(cVar38 == cVar20);
      uVar3 = (ushort)(SUB161(auVar35 >> 7,0) & 1) | (ushort)(SUB161(auVar35 >> 0xf,0) & 1) << 1 |
              (ushort)(SUB161(auVar35 >> 0x17,0) & 1) << 2 |
              (ushort)(SUB161(auVar35 >> 0x1f,0) & 1) << 3 |
              (ushort)(SUB161(auVar35 >> 0x27,0) & 1) << 4 |
              (ushort)(SUB161(auVar35 >> 0x2f,0) & 1) << 5 |
              (ushort)(SUB161(auVar35 >> 0x37,0) & 1) << 6 |
              (ushort)(SUB161(auVar35 >> 0x3f,0) & 1) << 7 |
              (ushort)(SUB161(auVar35 >> 0x47,0) & 1) << 8 |
              (ushort)(SUB161(auVar35 >> 0x4f,0) & 1) << 9 |
              (ushort)(SUB161(auVar35 >> 0x57,0) & 1) << 10 |
              (ushort)(SUB161(auVar35 >> 0x5f,0) & 1) << 0xb |
              (ushort)(SUB161(auVar35 >> 0x67,0) & 1) << 0xc |
              (ushort)(SUB161(auVar35 >> 0x6f,0) & 1) << 0xd |
              (ushort)(SUB161(auVar35 >> 0x77,0) & 1) << 0xe | (ushort)(auVar35[0xf] >> 7) << 0xf;
      uVar30 = (uint)uVar3;
      if (uVar3 != 0) {
        do {
          uVar1 = 0;
          if (uVar30 != 0) {
            for (; (uVar30 >> uVar1 & 1) == 0; uVar1 = uVar1 + 1) {
            }
          }
          uVar32 = uVar1 + uVar28 & uVar33;
          lVar29 = uVar32 * 0x18;
          cVar21 = FUN_140115980(*(longlong *)(param_1 + 0x40) + lVar29,&local_88);
          if (cVar21 != '\0') {
            lVar29 = *(longlong *)(param_1 + 0x40) + lVar29;
            lVar23 = *(longlong *)(param_1 + 0x38);
            lVar34 = lVar23 + uVar32;
            lVar26 = *(longlong *)(param_1 + 0x50);
            goto LAB_14048729c;
          }
          uVar30 = uVar30 & uVar30 - 1;
        } while (uVar30 != 0);
        lVar23 = *(longlong *)(param_1 + 0x38);
      }
      auVar39[0] = -(cVar5 == DAT_140fa49d0);
      auVar39[1] = -(cVar6 == UNK_140fa49d1);
      auVar39[2] = -(cVar7 == UNK_140fa49d2);
      auVar39[3] = -(cVar8 == UNK_140fa49d3);
      auVar39[4] = -(cVar9 == UNK_140fa49d4);
      auVar39[5] = -(cVar10 == UNK_140fa49d5);
      auVar39[6] = -(cVar11 == UNK_140fa49d6);
      auVar39[7] = -(cVar12 == UNK_140fa49d7);
      auVar39[8] = -(cVar13 == UNK_140fa49d8);
      auVar39[9] = -(cVar14 == UNK_140fa49d9);
      auVar39[10] = -(cVar15 == UNK_140fa49da);
      auVar39[0xb] = -(cVar16 == UNK_140fa49db);
      auVar39[0xc] = -(cVar17 == UNK_140fa49dc);
      auVar39[0xd] = -(cVar18 == UNK_140fa49dd);
      auVar39[0xe] = -(cVar19 == UNK_140fa49de);
      auVar39[0xf] = -(cVar20 == UNK_140fa49df);
      if ((((((((((((((((auVar39 >> 7 & (undefined1  [16])0x1) != (undefined1  [16])0x0 ||
                       (auVar39 >> 0xf & (undefined1  [16])0x1) != (undefined1  [16])0x0) ||
                      (auVar39 >> 0x17 & (undefined1  [16])0x1) != (undefined1  [16])0x0) ||
                     (auVar39 >> 0x1f & (undefined1  [16])0x1) != (undefined1  [16])0x0) ||
                    (auVar39 >> 0x27 & (undefined1  [16])0x1) != (undefined1  [16])0x0) ||
                   (auVar39 >> 0x2f & (undefined1  [16])0x1) != (undefined1  [16])0x0) ||
                  (auVar39 >> 0x37 & (undefined1  [16])0x1) != (undefined1  [16])0x0) ||
                 (auVar39 >> 0x3f & (undefined1  [16])0x1) != (undefined1  [16])0x0) ||
                (auVar39 >> 0x47 & (undefined1  [16])0x1) != (undefined1  [16])0x0) ||
               (auVar39 >> 0x4f & (undefined1  [16])0x1) != (undefined1  [16])0x0) ||
              (auVar39 >> 0x57 & (undefined1  [16])0x1) != (undefined1  [16])0x0) ||
             (auVar39 >> 0x5f & (undefined1  [16])0x1) != (undefined1  [16])0x0) ||
            (auVar39 >> 0x67 & (undefined1  [16])0x1) != (undefined1  [16])0x0) ||
           (auVar39 >> 0x6f & (undefined1  [16])0x1) != (undefined1  [16])0x0) ||
          (auVar39 >> 0x77 & (undefined1  [16])0x1) != (undefined1  [16])0x0) ||
          cVar20 == UNK_140fa49df) break;
      uVar31 = uVar31 + 0x10;
      uVar28 = uVar28 + uVar31;
    }
    lVar26 = *(longlong *)(param_1 + 0x50);
    lVar34 = lVar23 + lVar26;
    lVar29 = CONCAT44(uStack_5c,local_60);
LAB_14048729c:
    if (lVar34 != lVar26 + lVar23) {
      uVar24 = *(ulonglong *)(lVar29 + 0x10);
    }
    if (((iStack_7c != 0) && ((local_80 & 0x80000000) == 0)) && (local_88 != (char *)0x0)) {
      LOCK();
      DAT_14143ea74 = DAT_14143ea74 + 1;
      UNLOCK();
      thunk_FUN_140cbe5f0();
    }
  }
  else {
    FUN_1401145b0(&local_78,param_2);
    FUN_140510640(&local_78,0x2f,0x5c);
    local_68 = "";
    if (*local_78 != '\0') {
      local_68 = local_78;
    }
    lVar23 = -1;
    do {
      lVar23 = lVar23 + 1;
    } while (local_78[lVar23] != '\0');
    local_60 = (uint)lVar23 & 0x7fffffff | local_70 & 0x80000000;
    uVar24 = FUN_140487040(param_1,&local_68);
    if ((local_6c != 0) && (-1 < (int)local_70)) {
      LOCK();
      DAT_14143ea74 = DAT_14143ea74 + 1;
      UNLOCK();
      thunk_FUN_140cbe5f0(local_78);
    }
  }
  return uVar24;
}

