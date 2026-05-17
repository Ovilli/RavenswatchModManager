// caller of text_localizer
// target: 0x14055d850
// caller fn: FUN_14055e830 @ 0x14055e830


/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */

void FUN_14055e830(longlong param_1,longlong param_2,int *param_3,undefined8 param_4,
                  longlong *param_5,longlong param_6)

{
  int iVar1;
  float fVar2;
  float fVar3;
  float fVar4;
  float fVar5;
  float fVar6;
  float fVar7;
  float fVar8;
  float fVar9;
  float fVar10;
  float fVar11;
  float fVar12;
  float fVar13;
  float fVar14;
  longlong lVar15;
  longlong lVar16;
  bool bVar17;
  float fVar18;
  float fVar19;
  float fVar20;
  float fVar21;
  float fVar22;
  float local_res8;
  undefined8 in_stack_fffffffffffffd98;
  undefined4 uVar24;
  undefined8 uVar23;
  undefined1 *puVar25;
  undefined4 uVar26;
  float local_238;
  float fStack_234;
  undefined4 uStack_230;
  float fStack_22c;
  char *local_228;
  uint local_220;
  int local_21c;
  float local_218;
  float local_214;
  float local_210 [2];
  float local_208;
  float fStack_204;
  undefined4 uStack_200;
  float fStack_1fc;
  undefined8 local_1f8;
  undefined8 uStack_1f0;
  float local_1e8;
  float local_1e4;
  undefined4 local_1e0;
  undefined8 local_1dc;
  uint local_1d4;
  undefined8 local_1c8;
  undefined8 uStack_1c0;
  undefined8 local_1b8;
  undefined8 uStack_1b0;
  undefined8 local_1a8;
  undefined8 uStack_1a0;
  undefined8 local_198;
  undefined8 uStack_190;
  undefined8 local_188;
  float fStack_180;
  float fStack_17c;
  undefined1 local_178 [16];
  longlong local_168 [3];
  undefined4 local_150;
  undefined2 local_14c;
  undefined1 local_14a;
  undefined4 local_148;
  undefined4 local_144;
  undefined4 local_140;
  undefined4 local_13c;
  undefined4 local_138;
  undefined8 local_128;
  undefined8 uStack_120;
  float local_118;
  float fStack_114;
  float fStack_110;
  float fStack_10c;
  float local_108;
  float fStack_104;
  float fStack_100;
  float fStack_fc;
  float local_f8;
  float fStack_f4;
  float fStack_f0;
  float fStack_ec;
  undefined1 local_e8;
  float local_d8;
  float fStack_d4;
  float fStack_d0;
  float fStack_cc;
  
  uVar24 = (undefined4)((ulonglong)in_stack_fffffffffffffd98 >> 0x20);
  local_1f8 = 0;
  uStack_1f0 = 0;
  FUN_140559d30(param_1,param_2,param_3,&local_1f8);
  fVar21 = (float)(param_3[1] + local_1f8._4_4_) * DAT_140fa4118;
  fVar19 = (float)(*param_3 + (int)local_1f8) * DAT_140fa3c48;
  fVar22 = (float)(param_3[1] + local_1f8._4_4_ + uStack_1f0._4_4_) * DAT_140fa4118;
  fVar20 = (float)(*param_3 + (int)local_1f8 + (int)uStack_1f0) * DAT_140fa3c48;
  local_218 = fVar19;
  local_214 = fVar21;
  lVar15 = FUN_140559f10(param_1);
  if (lVar15 == 0) {
    lVar15 = param_1 + 0x128;
  }
  lVar16 = *(longlong *)(lVar15 + 0x48);
  if (lVar16 == 0) {
    lVar16 = *(longlong *)(DAT_14140dde8 + 0x50);
  }
  local_res8 = (((float)*(int *)(param_2 + 0xc) * *(float *)(lVar15 + 0x60)) /
               (float)*(uint *)(lVar16 + 0x88)) * DAT_140fa3c48;
  fVar18 = fVar20;
  if (fVar20 <= fVar19) {
    fVar18 = fVar19;
  }
  fVar2 = fVar20;
  if (fVar19 <= fVar20) {
    fVar2 = fVar19;
  }
  fVar18 = fVar18 - fVar2;
  FUN_14055d850(param_1,&local_228);
  if (*(char *)(lVar15 + 0x65) != '\0') {
    FUN_14050ff40(&local_228);
  }
  lVar16 = *(longlong *)(lVar15 + 0x48);
  if (lVar16 == 0) {
    lVar16 = *(longlong *)(DAT_14140dde8 + 0x50);
  }
  puVar25 = local_178;
  uVar23 = CONCAT44(uVar24,0xffffffff);
  FUN_140641e00(local_210,lVar16,local_228,local_res8,uVar23,puVar25,0);
  uVar24 = (undefined4)((ulonglong)uVar23 >> 0x20);
  uVar26 = (undefined4)((ulonglong)puVar25 >> 0x20);
  iVar1 = *(int *)(lVar15 + 0x70);
  if (iVar1 == 1) {
    bVar17 = fVar18 < local_210[0];
LAB_14055ea6e:
    if (bVar17 || local_210[0] == fVar18) goto LAB_14055ea80;
  }
  else {
    if (iVar1 == 2) {
      bVar17 = local_210[0] < fVar18;
      goto LAB_14055ea6e;
    }
    if (iVar1 == 3) {
      lVar16 = *(longlong *)(lVar15 + 0x48);
      if (lVar16 == 0) {
        lVar16 = *(longlong *)(DAT_14140dde8 + 0x50);
      }
      uVar24 = (undefined4)((ulonglong)lVar16 >> 0x20);
      uVar26 = 0;
      local_res8 = (float)FUN_140527f50();
      goto LAB_14055ea80;
    }
    if (iVar1 != 4) goto LAB_14055ea80;
  }
  local_res8 = local_res8 * (fVar18 / local_210[0]);
LAB_14055ea80:
  local_1c8 = _DAT_140fa4210;
  uStack_1c0 = _UNK_140fa4218;
  local_1b8 = _DAT_140fa4250;
  uStack_1b0 = _UNK_140fa4258;
  local_1a8 = _DAT_140fa4470;
  uStack_1a0 = _UNK_140fa4478;
  local_198 = _DAT_140fa4840;
  uStack_190 = _UNK_140fa4848;
  local_1e4 = (fVar22 + fVar21) * DAT_140fa3cf4;
  local_1e8 = (fVar20 + fVar19) * DAT_140fa3cf4;
  local_1e0 = 0;
  local_1d4 = *(uint *)(param_1 + 0x18) ^ DAT_140fa49c0;
  local_1dc = 0;
  FUN_1404c9fd0(&local_1c8,&local_1dc,&local_1e8);
  local_168[1] = 0;
  local_168[2] = 0;
  local_150 = 0x101;
  local_14c = 1;
  local_148 = DAT_140fa3d60;
  local_14a = 1;
  fVar19 = *(float *)(param_6 + 0x90);
  fVar21 = *(float *)(param_6 + 0x94);
  fVar18 = *(float *)(param_6 + 0x98);
  fVar2 = *(float *)(param_6 + 0x9c);
  fVar3 = *(float *)(param_6 + 0xa0);
  fVar4 = *(float *)(param_6 + 0xa4);
  fVar5 = *(float *)(param_6 + 0xa8);
  fVar6 = *(float *)(param_6 + 0xac);
  fStack_1fc = (float)local_1b8;
  local_d8 = (float)local_198;
  fStack_d4 = (float)local_198;
  fStack_d0 = (float)local_198;
  fStack_cc = (float)local_198;
  fVar7 = *(float *)(param_6 + 0x80);
  fVar8 = *(float *)(param_6 + 0x84);
  fVar9 = *(float *)(param_6 + 0x88);
  fVar10 = *(float *)(param_6 + 0x8c);
  local_188._0_4_ = (float)*(undefined8 *)(param_6 + 0x70);
  local_188._4_4_ = (float)((ulonglong)*(undefined8 *)(param_6 + 0x70) >> 0x20);
  fStack_180 = (float)*(undefined8 *)(param_6 + 0x78);
  fStack_17c = (float)((ulonglong)*(undefined8 *)(param_6 + 0x78) >> 0x20);
  fStack_22c = (float)local_1c8 * fStack_17c + local_1c8._4_4_ * fVar10 +
               (float)uStack_1c0 * fVar2 + uStack_1c0._4_4_ * fVar6;
  fVar11 = *(float *)(param_6 + 0x70);
  fVar12 = *(float *)(param_6 + 0x74);
  fVar13 = *(float *)(param_6 + 0x78);
  fVar14 = *(float *)(param_6 + 0x7c);
  local_118 = (float)local_1b8 * fVar11 + local_1b8._4_4_ * fVar7 +
              (float)uStack_1b0 * fVar19 + uStack_1b0._4_4_ * fVar3;
  fStack_114 = (float)local_1b8 * fVar12 + local_1b8._4_4_ * fVar8 +
               (float)uStack_1b0 * fVar21 + uStack_1b0._4_4_ * fVar4;
  fStack_110 = (float)local_1b8 * fVar13 + local_1b8._4_4_ * fVar9 +
               (float)uStack_1b0 * fVar18 + uStack_1b0._4_4_ * fVar5;
  fStack_10c = (float)local_1b8 * fVar14 + local_1b8._4_4_ * fVar10 +
               (float)uStack_1b0 * fVar2 + uStack_1b0._4_4_ * fVar6;
  local_108 = (float)local_1a8 * fVar11 + local_1a8._4_4_ * fVar7 +
              (float)uStack_1a0 * fVar19 + uStack_1a0._4_4_ * fVar3;
  fStack_104 = (float)local_1a8 * fVar12 + local_1a8._4_4_ * fVar8 +
               (float)uStack_1a0 * fVar21 + uStack_1a0._4_4_ * fVar4;
  fStack_100 = (float)local_1a8 * fVar13 + local_1a8._4_4_ * fVar9 +
               (float)uStack_1a0 * fVar18 + uStack_1a0._4_4_ * fVar5;
  fStack_fc = (float)local_1a8 * fVar14 + local_1a8._4_4_ * fVar10 +
              (float)uStack_1a0 * fVar2 + uStack_1a0._4_4_ * fVar6;
  local_f8 = (float)local_198 * fVar11 + local_198._4_4_ * fVar7 +
             (float)uStack_190 * fVar19 + uStack_190._4_4_ * fVar3;
  fStack_f4 = (float)local_198 * fVar12 + local_198._4_4_ * fVar8 +
              (float)uStack_190 * fVar21 + uStack_190._4_4_ * fVar4;
  fStack_f0 = (float)local_198 * fVar13 + local_198._4_4_ * fVar9 +
              (float)uStack_190 * fVar18 + uStack_190._4_4_ * fVar5;
  fStack_ec = (float)local_198 * fVar14 + local_198._4_4_ * fVar10 +
              (float)uStack_190 * fVar2 + uStack_190._4_4_ * fVar6;
  local_128 = CONCAT44((float)local_1c8 * local_188._4_4_ + local_1c8._4_4_ * fVar8 +
                       (float)uStack_1c0 * fVar21 + uStack_1c0._4_4_ * fVar4,
                       (float)local_1c8 * (float)local_188 + local_1c8._4_4_ * fVar7 +
                       (float)uStack_1c0 * fVar19 + uStack_1c0._4_4_ * fVar3);
  uStack_120 = CONCAT44(fStack_22c,
                        (float)local_1c8 * fStack_180 + local_1c8._4_4_ * fVar9 +
                        (float)uStack_1c0 * fVar18 + uStack_1c0._4_4_ * fVar5);
  local_144 = *(undefined4 *)(lVar15 + 0x50);
  local_140 = *(undefined4 *)(lVar15 + 0x54);
  local_13c = *(undefined4 *)(lVar15 + 0x58);
  local_138 = *(undefined4 *)(lVar15 + 0x5c);
  local_168[0] = *(longlong *)(lVar15 + 0x48);
  if (local_168[0] == 0) {
    local_168[0] = *(longlong *)(DAT_14140dde8 + 0x50);
  }
  local_e8 = 0;
  uStack_200 = 0;
  local_238 = local_218;
  fStack_234 = local_214;
  uStack_230 = 0;
  local_188 = "";
  if (*local_228 != '\0') {
    local_188 = local_228;
  }
  lVar16 = -1;
  do {
    lVar16 = lVar16 + 1;
  } while (local_228[lVar16] != '\0');
  _fStack_180 = CONCAT44(fStack_17c,(uint)lVar16 & 0x7fffffff | local_220 & 0x80000000);
  local_208 = fVar20;
  fStack_204 = fVar22;
  (**(code **)(*param_5 + 0x130))
            (param_5,&local_188,&local_238,&local_208,
             CONCAT44(uVar24,*(undefined4 *)(lVar15 + 0x68)),
             CONCAT44(uVar26,*(undefined4 *)(lVar15 + 0x6c)),1,local_res8,
             *(undefined1 *)(lVar15 + 100),local_168);
  if (((local_21c != 0) && ((local_220 & 0x80000000) == 0)) && (local_228 != (char *)0x0)) {
    LOCK();
    DAT_14143ea74 = DAT_14143ea74 + 1;
    UNLOCK();
    thunk_FUN_140cbe5f0();
  }
  return;
}

