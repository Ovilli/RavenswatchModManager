// bookmenu_tab_handler
// caller site (link va): 0x14048c520
// containing function: FUN_14048c490 @ 0x14048c490


void FUN_14048c490(longlong *param_1,longlong param_2,longlong param_3,ulonglong param_4,
                  longlong *param_5,undefined8 param_6)

{
  undefined8 *puVar1;
  undefined8 *puVar2;
  undefined8 uVar3;
  bool bVar4;
  char cVar5;
  uint uVar6;
  int iVar7;
  longlong lVar8;
  ulonglong uVar9;
  longlong lVar10;
  ulonglong *puVar11;
  char *pcVar12;
  char **ppcVar13;
  char *pcVar14;
  longlong *plVar15;
  char *pcVar16;
  uint uVar17;
  uint uVar18;
  char *pcVar19;
  uint uVar20;
  longlong lVar21;
  longlong local_res10;
  char *local_d0;
  uint local_c8;
  uint local_c4;
  char *local_c0;
  uint local_b8;
  char *local_a8;
  uint local_a0;
  longlong local_98;
  int local_90;
  int local_8c;
  longlong local_88;
  int local_80;
  int local_7c;
  undefined8 local_78;
  undefined1 local_70;
  char *local_68;
  uint local_60;
  char *local_58;
  uint local_50;
  char *local_48;
  uint local_40;
  
  bVar4 = false;
  lVar21 = -1;
  lVar8 = param_2;
  do {
    local_res10 = lVar8;
    EnterCriticalSection((LPCRITICAL_SECTION)(local_res10 + 0x70));
    pcVar16 = *(char **)(param_3 + 0x10);
    local_68 = "";
    if (*pcVar16 != '\0') {
      local_68 = pcVar16;
    }
    lVar8 = -1;
    do {
      lVar8 = lVar8 + 1;
    } while (pcVar16[lVar8] != '\0');
    local_60 = ((uint)lVar8 ^ *(uint *)(param_3 + 0x18)) & 0x7fffffff ^ *(uint *)(param_3 + 0x18);
    ppcVar13 = &local_68;
    uVar9 = FUN_140487040(local_res10,ppcVar13);
    if (uVar9 != 0) goto LAB_14048ca5f;
    lVar8 = *(longlong *)(local_res10 + 0xb8);
  } while (*(longlong *)(local_res10 + 0xb8) != 0);
  if ((param_4 >> 4 & 1) != 0) {
    pcVar16 = *(char **)(param_3 + 0x10);
    pcVar14 = pcVar16;
    if (*pcVar16 == '\0') {
      pcVar14 = "";
    }
    lVar8 = -1;
    do {
      lVar8 = lVar8 + 1;
    } while (pcVar16[lVar8] != '\0');
    uVar17 = (uint)lVar8;
    for (pcVar12 = pcVar14 + (uVar17 & 0x7fffffff); pcVar14 <= pcVar12; pcVar12 = pcVar12 + -1) {
      if (*pcVar12 == '\\') {
        pcVar19 = "";
        if (*pcVar12 != '\0') {
          pcVar19 = pcVar12;
        }
        uVar17 = (uVar17 & 0x7fffffff ^ ((uVar17 & 0x7fffffff) - (int)pcVar12) + (int)pcVar14) &
                 0x7fffffff ^ uVar17 & 0x7fffffff;
        goto LAB_14048c5ab;
      }
    }
    pcVar19 = "";
    uVar17 = 0;
LAB_14048c5ab:
    if (*pcVar19 == '\0') {
      pcVar19 = "";
      if (*pcVar16 != '\0') {
        pcVar19 = pcVar16;
      }
      lVar8 = -1;
      do {
        lVar8 = lVar8 + 1;
      } while (pcVar16[lVar8] != '\0');
      uVar17 = (uint)lVar8 & 0x7fffffff;
    }
    else if (uVar17 == 1) {
      pcVar19 = "";
      uVar17 = 0;
    }
    else {
      pcVar19 = pcVar19 + 1;
      uVar17 = uVar17 ^ (uVar17 - 1 ^ uVar17) & 0x7fffffff;
    }
    for (puVar1 = *(undefined8 **)(DAT_141446aa8 + 8); puVar1 != (undefined8 *)0xffffffffffffffff;
        puVar1 = (undefined8 *)*puVar1) {
      FUN_140486f80(puVar1 + 2);
      for (puVar2 = (undefined8 *)puVar1[5]; puVar2 != (undefined8 *)0xffffffffffffffff;
          puVar2 = (undefined8 *)*puVar2) {
        pcVar16 = (char *)puVar2[5];
        pcVar14 = "";
        if (*pcVar16 != '\0') {
          pcVar14 = pcVar16;
        }
        lVar8 = -1;
        do {
          lVar8 = lVar8 + 1;
        } while (pcVar16[lVar8] != '\0');
        uVar6 = (uint)lVar8 & 0x7fffffff;
        if ((uVar17 <= uVar6) &&
           (iVar7 = FUN_140ca7740(pcVar14 + (uVar6 - uVar17),pcVar19), iVar7 == 0)) {
          lVar8 = puVar2[2];
          uVar3 = *(undefined8 *)(param_3 + 0x20);
          pcVar16 = (char *)puVar2[5];
          local_a8 = pcVar16;
          if (*pcVar16 == '\0') {
            local_a8 = "";
          }
          pcVar14 = local_a8;
          lVar10 = -1;
          do {
            lVar10 = lVar10 + 1;
          } while (pcVar16[lVar10] != '\0');
          local_a0 = ((uint)lVar10 ^ *(uint *)(puVar2 + 6)) & 0x7fffffff ^ *(uint *)(puVar2 + 6);
          pcVar16 = *(char **)(lVar8 + 0x98);
          pcVar12 = "";
          if (*pcVar16 != '\0') {
            pcVar12 = pcVar16;
          }
          do {
            lVar21 = lVar21 + 1;
          } while (pcVar16[lVar21] != '\0');
          local_b8 = ((uint)lVar21 ^ *(uint *)(lVar8 + 0xa0)) & 0x7fffffff ^ *(uint *)(lVar8 + 0xa0)
          ;
          local_c0 = pcVar12;
          FUN_1401145b0(&local_98,&local_c0);
          FUN_1401145b0(&local_88,&local_a8);
          if ((*pcVar12 == '\0') && (*pcVar14 == '\0')) {
            local_70 = 1;
          }
          else {
            local_70 = 0;
          }
          local_78 = uVar3;
          FUN_14048c490(param_1,lVar8,&local_98,param_4,param_5,param_6);
          local_70 = 1;
          if (((local_7c != 0) && (-1 < local_80)) && (local_88 != 0)) {
            LOCK();
            DAT_14143ea74 = DAT_14143ea74 + 1;
            UNLOCK();
            thunk_FUN_140cbe5f0();
          }
          if (local_8c == 0) {
            return;
          }
          if (local_90 < 0) {
            return;
          }
          if (local_98 == 0) {
            return;
          }
          LOCK();
          DAT_14143ea74 = DAT_14143ea74 + 1;
          UNLOCK();
          thunk_FUN_140cbe5f0();
          return;
        }
      }
    }
  }
  pcVar16 = *(char **)(local_res10 + 0xd8);
  local_c0 = "";
  if (*pcVar16 != '\0') {
    local_c0 = pcVar16;
  }
  lVar8 = -1;
  do {
    lVar8 = lVar8 + 1;
  } while (pcVar16[lVar8] != '\0');
  local_b8 = ((uint)lVar8 ^ *(uint *)(local_res10 + 0xe0)) & 0x7fffffff ^
             *(uint *)(local_res10 + 0xe0);
  FUN_1401145b0(&local_d0,&local_c0);
  pcVar16 = *(char **)(param_3 + 0x10);
  pcVar14 = "";
  if (*pcVar16 != '\0') {
    pcVar14 = pcVar16;
  }
  lVar8 = -1;
  do {
    lVar8 = lVar8 + 1;
  } while (pcVar16[lVar8] != '\0');
  uVar6 = ((uint)lVar8 ^ *(uint *)(param_3 + 0x18)) & 0x7fffffff ^ *(uint *)(param_3 + 0x18);
  uVar20 = uVar6 & 0x7fffffff;
  pcVar16 = local_d0;
  uVar17 = local_c8;
  if (uVar20 != 0) {
    uVar18 = local_c8 & 0x7fffffff;
    if (uVar18 == 0) {
      if ((int)uVar6 < 0) {
        if ((-1 < (int)local_c8) && (local_d0 != (char *)0x0)) {
          LOCK();
          DAT_14143ea74 = DAT_14143ea74 + 1;
          UNLOCK();
          thunk_FUN_140cbe5f0(local_d0);
        }
        local_c4 = 0;
        local_c8 = 0x80000000;
        pcVar16 = pcVar14;
        local_d0 = pcVar14;
      }
      else {
        pcVar12 = local_d0;
        if (local_c4 < uVar20) {
          pcVar12 = (char *)FUN_140510c80(&local_d0,uVar20);
        }
        pcVar16 = local_d0;
        FUN_140c96e80(pcVar12,pcVar14,uVar20 + 1);
      }
      local_c8 = local_c8 ^ (local_c8 ^ uVar20) & 0x7fffffff;
      uVar17 = local_c8;
    }
    else {
      uVar17 = uVar20 + uVar18;
      if (uVar17 == 0) {
        if ((-1 < (int)local_c8) && (local_d0 != (char *)0x0)) {
          LOCK();
          DAT_14143ea74 = DAT_14143ea74 + 1;
          UNLOCK();
          thunk_FUN_140cbe5f0(local_d0);
        }
        local_d0 = "";
        local_c8 = 0x80000000;
        local_c4 = 0;
        pcVar12 = (char *)0x0;
      }
      else {
        pcVar12 = local_d0;
        if (local_c4 < uVar17) {
          pcVar12 = (char *)FUN_140510c80(&local_d0,uVar17);
        }
      }
      pcVar16 = local_d0;
      uVar17 = local_c8 ^ (local_c8 ^ uVar17) & 0x7fffffff;
      local_c8 = uVar17;
      FUN_140c96e80(pcVar12 + uVar18,pcVar14,uVar20 + 1);
    }
  }
  bVar4 = true;
  pcVar14 = *(char **)(param_3 + 0x10);
  local_58 = "";
  if (*pcVar14 != '\0') {
    local_58 = pcVar14;
  }
  lVar8 = -1;
  do {
    lVar8 = lVar8 + 1;
  } while (pcVar14[lVar8] != '\0');
  local_50 = ((uint)lVar8 ^ *(uint *)(param_3 + 0x18)) & 0x7fffffff ^ *(uint *)(param_3 + 0x18);
  local_48 = "";
  if (*pcVar16 != '\0') {
    local_48 = pcVar16;
  }
  lVar8 = -1;
  do {
    lVar8 = lVar8 + 1;
  } while (pcVar16[lVar8] != '\0');
  local_40 = (uint)lVar8 & 0x7fffffff | uVar17 & 0x80000000;
  ppcVar13 = &local_48;
  uVar9 = FUN_140487300(local_res10,ppcVar13,&local_58);
  if ((local_c4 != 0) && (-1 < (int)uVar17)) {
    LOCK();
    DAT_14143ea74 = DAT_14143ea74 + 1;
    UNLOCK();
    thunk_FUN_140cbe5f0(local_d0);
  }
LAB_14048ca5f:
  LeaveCriticalSection((LPCRITICAL_SECTION)(local_res10 + 0x70));
  puVar11 = (ulonglong *)(**(code **)(*param_1 + 0x28))(param_1);
  puVar11[9] = uVar9;
  puVar11[5] = param_4;
  if (!bVar4) {
    if ((param_4 >> 3 & 1) == 0) {
      ppcVar13 = (char **)*puVar11;
      cVar5 = (*(code *)ppcVar13[0x19])(puVar11);
      if (cVar5 == '\0') goto LAB_14048caab;
      uVar9 = 1;
    }
    else {
LAB_14048caab:
      uVar9 = (ulonglong)ppcVar13 & 0xffffffffffffff00;
    }
    cVar5 = FUN_14048e1e0(puVar11,uVar9);
    LOCK();
    *(undefined4 *)(puVar11 + 7) = 1;
    UNLOCK();
    if (cVar5 == '\x01') goto LAB_14048cae1;
    bVar4 = true;
  }
  (**(code **)(*puVar11 + 0x40))(puVar11);
  (**(code **)(*puVar11 + 0xb0))(puVar11);
  (**(code **)(*puVar11 + 0x48))(puVar11);
LAB_14048cae1:
  FUN_14048d980(param_1,puVar11);
  if ((param_4 & 1) != 0) {
    cVar5 = (**(code **)(*puVar11 + 0x90))(puVar11);
    if (cVar5 == '\x01') {
      LOCK();
      *(undefined4 *)((longlong)puVar11 + 0x3c) = 1;
      UNLOCK();
    }
    else {
      LOCK();
      *(undefined4 *)((longlong)puVar11 + 0x3c) = 0;
      UNLOCK();
    }
  }
  if (bVar4) {
    (**(code **)(*puVar11 + 0x58))(puVar11);
  }
  lVar8 = *param_5;
  if (lVar8 != 0) {
    plVar15 = (longlong *)(lVar8 + 8);
    LOCK();
    lVar21 = *plVar15;
    *plVar15 = *plVar15 + -1;
    UNLOCK();
    if ((lVar21 == 1) && (*(longlong **)(lVar8 + 0x10) != (longlong *)0x0)) {
      (**(code **)(**(longlong **)(lVar8 + 0x10) + 8))();
    }
  }
  *param_5 = (longlong)puVar11;
  LOCK();
  puVar11[1] = puVar11[1] + 1;
  UNLOCK();
  return;
}

